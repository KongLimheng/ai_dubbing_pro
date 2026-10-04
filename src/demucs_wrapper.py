#!/usr/bin/env python
import json
import sys
import wave
from pathlib import Path


def _force_utf8_stdio():
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _inject_shims():
    base_dir = Path(__file__).resolve().parent
    shim_dir = base_dir / "vendor_shims"
    if shim_dir.exists():
        shim_path = str(shim_dir)
        if shim_path not in sys.path:
            sys.path.insert(0, shim_path)


def _write_wav_with_stdlib(path, audio_array, samplerate, bits_per_sample=16, as_float=False):
    """
    Write PCM WAV without optional third-party audio libraries.

    Demucs normally emits WAV stems, so this keeps separation working even when
    the runtime is missing `soundfile`.
    """
    bits_per_sample = 32 if as_float else int(bits_per_sample or 16)
    if bits_per_sample not in (16, 24, 32):
        bits_per_sample = 16

    clipped = audio_array.clip(-1.0, 1.0)

    if bits_per_sample == 16:
        pcm = (clipped * 32768.0).round().clip(-32768, 32767).astype("<i2", copy=False)
        raw_bytes = pcm.tobytes()
    elif bits_per_sample == 24:
        pcm = (clipped * 8388608.0).round().clip(-8388608, 8388607).astype("<i4", copy=False)
        raw_bytes = pcm.view("uint8").reshape(-1, 4)[:, :3].tobytes()
    else:
        # The stdlib wave module only writes PCM, so float output degrades to
        # 32-bit PCM when `soundfile` is unavailable.
        pcm = (clipped * 2147483648.0).round().clip(-2147483648, 2147483647).astype("<i4", copy=False)
        raw_bytes = pcm.tobytes()

    channels = 1 if audio_array.ndim == 1 else int(audio_array.shape[1])

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(bits_per_sample // 8)
        wav_file.setframerate(int(samplerate))
        wav_file.writeframes(raw_bytes)


def _patch_audio_saving():
    from demucs import audio as demucs_audio
    from demucs import separate as demucs_separate

    try:
        import soundfile as sf
    except Exception:
        sf = None

    def patched_save_audio(
        wav,
        path,
        samplerate,
        bitrate=320,
        clip="rescale",
        bits_per_sample=16,
        as_float=False,
        preset=2,
    ):
        wav = demucs_audio.prevent_clip(wav, mode=clip)
        path = Path(path)
        suffix = path.suffix.lower()

        if suffix == ".mp3":
            demucs_audio.encode_mp3(wav, path, samplerate, bitrate, preset, verbose=True)
            return

        if hasattr(wav, "detach"):
            wav = wav.detach().cpu()
        if wav.ndim == 1:
            wav = wav.unsqueeze(0)

        audio_array = wav.transpose(0, 1).contiguous().numpy()

        if suffix == ".wav":
            if sf is None:
                _write_wav_with_stdlib(
                    path,
                    audio_array,
                    samplerate,
                    bits_per_sample=bits_per_sample,
                    as_float=as_float,
                )
                return

            if as_float:
                subtype = "FLOAT"
            elif bits_per_sample == 24:
                subtype = "PCM_24"
            elif bits_per_sample == 32:
                subtype = "PCM_32"
            else:
                subtype = "PCM_16"
            sf.write(str(path), audio_array, samplerate, format="WAV", subtype=subtype)
            return

        if suffix == ".flac":
            if sf is None:
                raise RuntimeError("Saving FLAC output requires the optional 'soundfile' package.")
            subtype = "PCM_24" if bits_per_sample == 24 else "PCM_16"
            sf.write(str(path), audio_array, samplerate, format="FLAC", subtype=subtype)
            return

        raise ValueError(f"Invalid suffix for path: {suffix}")

    demucs_audio.save_audio = patched_save_audio
    demucs_separate.save_audio = patched_save_audio


def _patch_torch_load():
    import torch

    original_torch_load = torch.load

    def patched_torch_load(*args, **kwargs):
        # Demucs checkpoints are trusted app assets. PyTorch 2.6+ defaults to
        # weights_only=True, which breaks these serialized model packages.
        kwargs["weights_only"] = False
        return original_torch_load(*args, **kwargs)

    torch.load = patched_torch_load


def _probe_runtime():
    payload = {
        "ok": False,
        "demucs_importable": False,
        "torch_importable": False,
        "gpu_available": False,
        "cuda_available": False,
        "cuda_device_count": 0,
        "cuda_device_name": None,
        "preferred_device": "cpu",
        "device_backend": "cpu",
        "torch_version": None,
        "torch_cuda_version": None,
        "torch_hip_version": None,
        "torch_xpu_available": False,
        "torch_mps_available": False,
    }

    try:
        import demucs

        payload["demucs_importable"] = True
        payload["demucs_version"] = getattr(demucs, "__version__", "")
    except Exception as exc:
        payload["error"] = f"demucs import failed: {exc}"

    try:
        import torch

        payload["torch_importable"] = True
        payload["torch_version"] = getattr(torch, "__version__", "")
        payload["torch_cuda_version"] = getattr(torch.version, "cuda", None)
        payload["torch_hip_version"] = getattr(torch.version, "hip", None)

        if hasattr(torch, "cuda") and torch.cuda.is_available():
            try:
                # Verify that CUDA kernels can actually execute on this GPU architecture
                # (prevents false positives on older GPUs like Pascal sm_61 when modern torch lacks kernels)
                _test_cuda = torch.zeros(1, device="cuda")
                payload["gpu_available"] = True
                payload["cuda_available"] = True
                payload["preferred_device"] = "cuda"
                payload["device_backend"] = "hip" if payload["torch_hip_version"] else "cuda"
                payload["cuda_device_count"] = int(torch.cuda.device_count())
                try:
                    payload["cuda_device_name"] = torch.cuda.get_device_name(0)
                except Exception as exc:
                    payload["cuda_name_error"] = str(exc)
            except Exception as _cuda_exec_err:
                payload["gpu_available"] = False
                payload["cuda_available"] = False
                payload["preferred_device"] = "cpu"
                payload["device_backend"] = "cpu"
                payload["cuda_arch_unsupported"] = True
                payload["cuda_error"] = str(_cuda_exec_err)
                try:
                    payload["cuda_device_name"] = torch.cuda.get_device_name(0)
                except Exception:
                    pass
        else:
            xpu = getattr(torch, "xpu", None)
            if xpu and hasattr(xpu, "is_available") and xpu.is_available():
                payload["gpu_available"] = True
                payload["cuda_available"] = True
                payload["torch_xpu_available"] = True
                payload["preferred_device"] = "xpu"
                payload["device_backend"] = "xpu"
                if hasattr(xpu, "device_count"):
                    payload["cuda_device_count"] = int(xpu.device_count())
                try:
                    if hasattr(xpu, "get_device_name"):
                        payload["cuda_device_name"] = xpu.get_device_name(0)
                except Exception as exc:
                    payload["xpu_name_error"] = str(exc)
            elif (
                hasattr(torch, "backends")
                and hasattr(torch.backends, "mps")
                and torch.backends.mps.is_available()
            ):
                payload["gpu_available"] = True
                payload["cuda_available"] = True
                payload["torch_mps_available"] = True
                payload["preferred_device"] = "mps"
                payload["device_backend"] = "mps"
                payload["cuda_device_count"] = 1
                payload["cuda_device_name"] = "Apple Metal"
    except Exception as exc:
        payload["torch_error"] = str(exc)

    payload["ok"] = bool(payload["demucs_importable"] and payload["torch_importable"])
    return payload


def main():
    _force_utf8_stdio()
    _inject_shims()
    if len(sys.argv) > 1 and sys.argv[1] == "--probe-runtime":
        print(json.dumps(_probe_runtime()))
        return 0

    _patch_torch_load()
    _patch_audio_saving()
    from demucs.separate import main as demucs_main

    return demucs_main(sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
