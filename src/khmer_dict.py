# Source Generated with Decompyle++
# File: khmer_dict.pyc (Python 3.11)

'''
Khmer pronunciation helpers for translation and TTS cleanup.

This file keeps lightweight, safe replacements that make Khmer dubbing sound
more natural after machine translation. The goal is to improve spoken output
without changing the broader app logic.
'''
ASCII_TO_KHMER_DIGITS = str.maketrans('0123456789', '០១២៣៤៥៦៧៨៩')
KHMER_DIGIT_WORDS = {
    0: 'សូន្យ',
    1: 'មួយ',
    2: 'ពីរ',
    3: 'បី',
    4: 'បួន',
    5: 'ប្រាំ',
    6: 'ប្រាំមួយ',
    7: 'ប្រាំពីរ',
    8: 'ប្រាំបី',
    9: 'ប្រាំបួន' }
KHMER_TENS_WORDS = {
    2: 'ម្ភៃ',
    3: 'សាមសិប',
    4: 'សែសិប',
    5: 'ហាសិប',
    6: 'ហុកសិប',
    7: 'ចិតសិប',
    8: 'ប៉ែតសិប',
    9: 'កៅសិប' }
KHMER_SCALE_WORDS = ((1000000, 'លាន'), (100000, 'សែន'), (10000, 'ម៉ឺន'), (1000, 'ពាន់'), (100, 'រយ'))

def _to_khmer_digit_string(number):
    return str(number).translate(ASCII_TO_KHMER_DIGITS)


def _int_to_khmer_words(number):
    if number < 10:
        return KHMER_DIGIT_WORDS[number]
    if None < 20:
        if number == 10:
            return 'ដប់'
        return None + KHMER_DIGIT_WORDS[number - 10]
    if None < 100:
        (tens, ones) = divmod(number, 10)
        base = KHMER_TENS_WORDS[tens]
        if ones:
            return base + KHMER_DIGIT_WORDS[ones]
        return None
    for scale_value, scale_name in None:
        if number >= scale_value:
            (major, remainder) = divmod(number, scale_value)
            base = _int_to_khmer_words(major) + scale_name
            if remainder:
                
                return None, base + _int_to_khmer_words(remainder)
            
            return None, None
        return str(number)


def _build_number_replacements():
    common_values = set(range(0, 121))
    common_values.update(range(130, 1001, 10))
    common_values.update(range(1900, 2101))
    common_values.update({
        20000,
        500000,
        30000,
        1080,
        40000,
        50000,
        360,
        365,
        2160,
        1440,
        720,
        480,
        10000,
        1000000,
        144,
        100000,
        240})
    replacements = { }
    for value in sorted(common_values):
        word = _int_to_khmer_words(value)
        replacements[str(value)] = word
        replacements[_to_khmer_digit_string(value)] = word
    return replacements

NUM_REPLACEMENTS = _build_number_replacements()
SORTED_NUM_REPLACEMENTS = tuple(sorted(NUM_REPLACEMENTS.items(), key = (lambda item: len(item[0])), reverse = True))
RELATION_FIXES = {
    'បងប្រុស និងបងស្រី': 'បងប្អូន',
    'ប្អូនប្រុសប្អូនស្រី': 'បងប្អូន',
    'បងប្រុសបងស្រី': 'បងប្អូន',
    'ឪពុកម្តាយរបស់ខ្ញុំ': 'ប៉ាម៉ាក់របស់ខ្ញុំ',
    'លោកតាលោកយាយ': 'លោកតាលោកយាយ',
    'ឪពុកម្តាយ': 'ប៉ាម៉ាក់',
    'ពូនិងមីង': 'អ៊ំៗ',
    'ក្មេងប្រុស': 'ប្អូនប្រុស',
    'ក្មេងស្រី': 'ប្អូនស្រី',
    'បុរស': 'បុរសម្នាក់',
    'ស្ត្រី': 'ស្ត្រីម្នាក់',
    'ប្រុស': 'បុរសម្នាក់',
    'ស្រី': 'ស្ត្រីម្នាក់' }
ROBOTIC_PHRASE_FIXES = {
    'រង់ចាំបន្តិច': 'ចាំបន្តិចសិន',
    'ប្រយ័ត្ន': 'ប្រយ័ត្នផង',
    'ចេញអោយឆ្ងាយ': 'ចេញអោយឆ្ងាយទៅ',
    'មិនអាចជឿបាន': 'មិនគួរអោយជឿសោះ',
    'មិនសមហេតុផល': 'មិនសមហេតុផលសោះ',
    'ធ្វើបានល្អ': 'ធ្វើបានល្អណាស់',
    'ឆាប់ឡើង': 'ឆាប់ឡើងបន្តិចទៅ',
    'គាត់ជា': 'គាត់គឺ',
    'ខ្ញុំជា': 'ខ្ញុំគឺ',
    'អ្នកជា': 'អ្នកគឺ',
    'វាជាការ': 'វាគឺជា',
    'នេះជា': 'នេះគឺ',
    'នោះជា': 'នោះគឺ' }
STRONG_LANGUAGE_FIXES = {
    'ទៅសម្លាប់ខ្លួនឯង': 'ទៅងាប់ទៅ',
    'មនុស្សល្ងីល្ងើ': 'អាល្ងង់',
    'ឆ្កួតមែនទេ': 'ឆ្កួតទេអី',
    'បិទមាត់': 'បិទមាត់ទៅ',
    'ទៅឋាននរក': 'ទៅងាប់ទៅ',
    'ឆ្កែញី': 'មីថោកទាប',
    'កូនកាត់': 'អាថោកទាប',
    'រន្ធគូថ': 'អាខ្មោចយក្ស',
    'រួមភេទ': 'ចង្រៃយ៍ពិត',
    'មនុស្សឆ្កួត': 'អាឆ្កួត',
    'លីលា': 'ឆ្កួតលីលា' }
EXCLAMATION_FIXES = {
    'អូព្រះជាម្ចាស់': 'ឱព្រះអើយ',
    'ព្រះជាម្ចាស់អើយ': 'ឱព្រះអើយ',
    'អូ៊ព្រះជាម្ចាស់': 'ឱព្រះអើយ',
    'ជំរាបសួរ': 'សួស្តី',
    'សូមអរគុណ': 'អរគុណ',
    'ខ្ញុំសុំទោស': 'សុំទោស',
    'អូ ខេ': 'អូខេ',
    'Okay': 'អូខេ',
    'okay': 'អូខេ',
    'OK': 'អូខេ',
    'ok': 'អូខេ' }
STORY_FIXES = {
    'អ្នកដឹងទេ': 'ឯងដឹងទេ',
    'ចៅហ្វាយចាស់': 'លោកម្ចាស់ចាស់',
    'ចៅហ្វាយ': 'លោកម្ចាស់',
    'ព្រះរាជា': 'ព្រះករុណា',
    'ព្រះនាង': 'ទ្រង់',
    'ព្រះអម្ចាស់': 'ព្រះអង្គម្ចាស់' }
TECH_TERM_FIXES = {
    'MP3': 'អឹម ភី បី',
    'MP4': 'អឹម ភី បួន',
    '4K': 'បួន ខេ',
    'AI': 'អេ អាយ' }
UNIT_FIXES = {
    'PM': 'ល្ងាច' }
ORDINAL_FIXES = {
    'ទី 10': 'ទី១០',
    'ទី 9': 'ទី៩',
    'ទី 8': 'ទី៨',
    'ទី 7': 'ទី៧',
    'ទី 6': 'ទី៦',
    'ទី 5': 'ទី៥',
    'ទី 4': 'ទី៤',
    'ទី 3': 'ទី៣',
    'ទី 2': 'ទី២',
    'ទី 1': 'ទី១' }
WORD_FIXES = { }
WORD_FIXES.update(RELATION_FIXES)
WORD_FIXES.update(ROBOTIC_PHRASE_FIXES)
WORD_FIXES.update(STRONG_LANGUAGE_FIXES)
WORD_FIXES.update(EXCLAMATION_FIXES)
WORD_FIXES.update(STORY_FIXES)
WORD_FIXES.update(TECH_TERM_FIXES)
WORD_FIXES.update(UNIT_FIXES)
WORD_FIXES.update(ORDINAL_FIXES)
SORTED_WORD_FIXES = tuple(sorted(WORD_FIXES.items(), key = (lambda item: len(item[0])), reverse = True))
