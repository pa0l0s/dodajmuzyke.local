
from pathlib import Path
from app.core.matching import clean_title, duration_score, confidence_from_scores
from app.core.paths import safe_filename, destination_for_match


def test_clean_title_removes_youtube_noise_and_brackets():
    assert clean_title('Daft Punk - One More Time [Official Video] (4K Remastered)') == 'Daft Punk - One More Time'


def test_clean_title_handles_lyrics_noise_case_insensitive():
    assert clean_title('Artist - Song Name (Lyric Video) HD') == 'Artist - Song Name'


def test_duration_score_tolerates_intro_outro_differences():
    assert duration_score(240, 248) >= 0.82
    assert duration_score(240, 310) < 0.70


def test_confidence_combines_fingerprint_text_and_duration():
    assert confidence_from_scores(fingerprint=0.92, text=0.7, duration=0.9) == 'high'
    assert confidence_from_scores(fingerprint=None, text=0.74, duration=0.84) == 'medium'
    assert confidence_from_scores(fingerprint=None, text=0.35, duration=0.5) == 'low'


def test_safe_filename_removes_forbidden_characters():
    assert safe_filename('AC/DC: Thunderstruck?') == 'AC_DC_ Thunderstruck'


def test_destination_for_matched_track_uses_navidrome_layout(tmp_path: Path):
    dest = destination_for_match(
        tmp_path,
        {
            'artist': 'Massive Attack',
            'album': 'Mezzanine',
            'title': 'Teardrop',
            'year': '1998',
            'track': '03',
            'confidence': 'high',
        },
        fallback_title='whatever'
    )
    assert dest == tmp_path / 'Massive Attack' / 'Mezzanine (1998)' / '03 - Teardrop.mp3'


def test_destination_for_unmatched_lives_inside_music_library(tmp_path: Path):
    dest = destination_for_match(tmp_path, None, fallback_title='Unknown [Official Video]')
    assert dest == tmp_path / '_Unmatched' / 'Unknown.mp3'
