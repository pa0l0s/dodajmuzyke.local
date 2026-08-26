from pathlib import Path

from app.core.matching import infer_metadata_suggestion, youtube_video_key
from app.core.media import (
    parse_yt_dlp_json,
    parse_yt_dlp_json_lines,
    youtube_download_args,
    youtube_info_args,
    youtube_search_args,
)
from app.core.state import JobStore
from app.worker import collect_known_artists


def test_youtube_video_key_normalizes_watch_short_and_embed_urls():
    assert youtube_video_key('https://youtu.be/HqLuWmW3CPM?si=abc') == 'youtube:HqLuWmW3CPM'
    assert youtube_video_key('https://www.youtube.com/watch?v=HqLuWmW3CPM&list=ignored') == 'youtube:HqLuWmW3CPM'
    assert youtube_video_key('https://www.youtube.com/embed/HqLuWmW3CPM') == 'youtube:HqLuWmW3CPM'


def test_youtube_video_key_for_plain_search_is_normalized_text():
    assert youtube_video_key('  Lej Mi Pół Aśnaebaem  ') == 'search:lej mi pół aśnaebaem'


def test_infer_metadata_suggestion_uses_description_artist_title_album_year():
    info = {
        'title': 'Official Video Noise',
        'upload_date': '20240512',
        'description': 'Artist: LEJ MI PÓŁ\nTitle: Aśnaebaem\nAlbum: Domowe VHS\nTrack: 7\n',
    }
    guess = infer_metadata_suggestion(info, 'fallback')
    assert guess['artist'] == 'LEJ MI PÓŁ'
    assert guess['title'] == 'Aśnaebaem'
    assert guess['album'] == 'Domowe VHS'
    assert guess['track'] == '07'
    assert guess['year'] == '2024'


def test_infer_metadata_suggestion_falls_back_to_cleaned_youtube_title_split():
    info = {'title': 'LEJ MI PÓŁ - Aśnaebaem (Oficjalna taśma VHS) (2024) #lejmipol'}
    guess = infer_metadata_suggestion(info, 'fallback')
    assert guess['artist'] == 'LEJ MI PÓŁ'
    assert guess['title'] == 'Aśnaebaem'
    assert guess['year'] == '2024'


def test_infer_metadata_suggestion_reads_youtube_music_block_and_polish_creator():
    info = {
        'title': 'Walenie i konie',
        'upload_date': '20250919',
        'description': '''187 577 wyświetleń  Data premiery: 19 wrz 2025
🎫 Kup płytę na: http://lejmipol.pl
Twórcy: Lej Mi Pół
Teledysk / Animacja: QT Studio

Muzyka
1 utwór

Walenie i konie
Lej Mi Pół
Walenie i konie''',
    }
    guess = infer_metadata_suggestion(info, 'fallback')
    assert guess['artist'] == 'Lej Mi Pół'
    assert guess['title'] == 'Walenie i konie'
    assert guess['year'] == '2025'


def test_infer_metadata_suggestion_reads_youtube_music_block_album_line():
    info = {
        'title': '"Veganka" - Lej Mi Pół (oficjalna taśma VHS)',
        'upload_date': '20170921',
        'description': '''Muzyka
1 utwór

Veganka
Lej Mi Pół
Wszystkiego Najlepszego Marian''',
    }
    guess = infer_metadata_suggestion(info, 'fallback')
    assert guess['artist'] == 'Lej Mi Pół'
    assert guess['title'] == 'Veganka'
    assert guess['album'] == 'Wszystkiego Najlepszego Marian'
    assert guess['year'] == '2017'


def test_infer_metadata_suggestion_prefers_youtube_music_block_over_other_description_labels():
    info = {
        'title': 'Chaotic promo title',
        'description': '''Twórcy: Video Studio

Muzyka
1 utwór

Veganka
Lej Mi Pół
Wszystkiego Najlepszego Marian''',
    }
    guess = infer_metadata_suggestion(info, 'fallback')
    assert guess['artist'] == 'Lej Mi Pół'
    assert guess['title'] == 'Veganka'
    assert guess['album'] == 'Wszystkiego Najlepszego Marian'


def test_infer_metadata_suggestion_uses_known_artist_to_reverse_title_artist_order():
    info = {'title': 'Veganka - Lej Mi Pół', 'known_artists': ['Lej Mi Pół', 'Massive Attack']}
    guess = infer_metadata_suggestion(info, 'fallback')
    assert guess['artist'] == 'Lej Mi Pół'
    assert guess['title'] == 'Veganka'


def test_infer_metadata_suggestion_handles_quoted_title_before_artist():
    info = {'title': '"Veganka" - Lej Mi Pół (oficjalna taśma VHS)', 'upload_date': '20170921'}
    guess = infer_metadata_suggestion(info, 'fallback')
    assert guess['artist'] == 'Lej Mi Pół'
    assert guess['title'] == 'Veganka'


def test_infer_metadata_suggestion_keeps_unknown_year_word_intact():
    guess = infer_metadata_suggestion({'title': 'Lej Mi Pół - Veganka'}, 'fallback')
    assert guess['year'] == 'Unknown'


def test_collect_known_artists_uses_library_folder_names_and_uploader(tmp_path: Path):
    (tmp_path / 'Lej Mi Pół').mkdir()
    (tmp_path / '_Unmatched').mkdir()
    (tmp_path / 'Massive Attack').mkdir()
    artists = collect_known_artists(tmp_path, extra=['YouTube Channel'])
    assert 'Lej Mi Pół' in artists
    assert 'Massive Attack' in artists
    assert 'YouTube Channel' in artists
    assert '_Unmatched' not in artists


def test_parse_yt_dlp_json_ignores_warning_lines_before_json():
    data = parse_yt_dlp_json('WARNING: missing JS runtime\n[youtube] noise\n{"title":"Walenie i konie","id":"Eja5ImsYO-M"}\n')
    assert data == {"title": "Walenie i konie", "id": "Eja5ImsYO-M"}


def test_parse_yt_dlp_json_lines_ignores_warnings_and_progress_lines():
    rows = parse_yt_dlp_json_lines('WARNING: missing JS runtime\n[youtube] searching\n{"title":"Veganka","id":"22oNZe1H2qI","webpage_url":"https://youtu.be/22oNZe1H2qI"}\n')
    assert rows == [{"title": "Veganka", "id": "22oNZe1H2qI", "webpage_url": "https://youtu.be/22oNZe1H2qI"}]


def test_youtube_search_uses_flat_playlist_and_ignores_unavailable_results():
    args = youtube_search_args('nabita lufa', 8)
    assert args[:2] == ['yt-dlp', 'ytsearch8:nabita lufa']
    assert '--flat-playlist' in args
    assert '--ignore-errors' in args
    assert '--no-warnings' in args


def test_youtube_info_and_download_explicitly_enable_node_runtime(tmp_path: Path):
    info_args = youtube_info_args('https://youtu.be/example')
    download_args = youtube_download_args('https://youtu.be/example', tmp_path)
    assert info_args[info_args.index('--js-runtimes') + 1] == 'node'
    assert download_args[download_args.index('--js-runtimes') + 1] == 'node'


def test_youtube_download_uses_mweb_po_token_provider_when_configured(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('DODAJMUZYKE_POT_PROVIDER_URL', 'http://bgutil-provider:4416')
    args = youtube_download_args('https://youtu.be/example', tmp_path)
    extractor_values = [args[i + 1] for i, value in enumerate(args) if value == '--extractor-args']
    assert 'youtube:player_client=mweb' in extractor_values
    assert 'youtubepot-bgutilhttp:base_url=http://bgutil-provider:4416' in extractor_values


def test_container_has_supported_node_and_matching_ejs_package():
    root = Path(__file__).parents[1]
    dockerfile = (root / 'Dockerfile').read_text()
    requirements = (root / 'requirements.txt').read_text()
    assert 'FROM node:22' in dockerfile
    assert 'yt-dlp[default]==2026.7.4' in requirements
    assert 'bgutil-ytdlp-pot-provider' in requirements


def test_job_store_reuses_existing_youtube_key_and_can_delete(tmp_path: Path):
    store = JobStore(tmp_path / 'jobs.sqlite3')
    job = store.create('youtube', 'x', source='https://youtu.be/HqLuWmW3CPM?si=abc', metadata={'youtube_key': 'youtube:HqLuWmW3CPM'})
    same = store.find_by_youtube_key('youtube:HqLuWmW3CPM')
    assert same['id'] == job['id']
    assert store.delete(job['id']) is True
    assert store.find_by_youtube_key('youtube:HqLuWmW3CPM') is None
