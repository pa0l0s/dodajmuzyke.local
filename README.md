# dodajmuzyke.local

Mobilna aplikacja webowa do dodawania muzyki do biblioteki Navidrome z YouTube albo z uploadu plików audio/archiwów.

Aplikacja:
- pobiera audio przez `yt-dlp`,
- konwertuje do MP3 VBR V0 przez `ffmpeg`,
- próbuje automatycznie ustalić `artist`, `title`, `album`, `year`, `track`,
- priorytetowo używa bloku YouTube `Muzyka`, bo tytuły filmów bywają niespójne,
- weryfikuje kolejność `artist/title` z tytułu filmu po znanych artystach z biblioteki,
- próbuje MusicBrainz/AcoustID/fpcalc,
- zapisuje tagi ID3,
- blokuje duplikaty YouTube po stałym video ID,
- przenosi dopasowane pliki do struktury Navidrome,
- pliki niepewne zostawia w `_Unmatched`, ale nadal wewnątrz biblioteki Navidrome.

## Jak używać

1. Otwórz aplikację:

```text
http://IP_SERWERA:8087
```

albo przez lokalny DNS/reverse proxy:

```text
http://dodajmuzyke.local
```

2. Zakładka `YouTube`:
- wklej URL YouTube i kliknij `Pobierz teraz`, albo
- wpisz frazę i kliknij `Szukaj`, potem `+` przy wybranym wyniku.

3. Zakładka `Upload`:
- wrzuć `mp3`, `wav`, `flac`, `m4a`, `zip` albo `rar`.

4. Zakładka `Kolejka`:
- kompaktowa lista zadań,
- kliknięcie w wiersz rozwija szczegóły,
- dla niepewnych utworów można ręcznie poprawić metadane,
- można usunąć zadanie z kolejki, jeśli nie jest aktualnie przetwarzane.

## Docelowy układ katalogów Navidrome

Kontener widzi bibliotekę jako:

```text
/music
```

Dopasowane utwory trafiają do:

```text
/music/{Artist}/{Album} ({Year})/{Track} - {Title}.mp3
```

Niedopasowane albo niepewne utwory trafiają do:

```text
/music/_Unmatched/{Oczyszczony_Tytuł}.mp3
```

Ważne: `_Unmatched` powinien być podfolderem tego samego katalogu, który indeksuje Navidrome. Przykład dla SMB/NAS:

```text
\\192.168.60.10\kuklenas\Music_Sorted
\\192.168.60.10\kuklenas\Music_Sorted\_Unmatched
```

## Instalacja w Dockerze

### 1. Sklonuj repozytorium

```bash
git clone git@github.com:pa0l0s/dodajmuzyke.local.git
cd dodajmuzyke.local
```

### 2. Przygotuj katalogi na hoście

Przykład:

```bash
sudo mkdir -p /srv/music/Music_Sorted
sudo mkdir -p /srv/docker/dodajmuzyke/downloads
```

Jeśli używasz OMV/NAS, podstaw realne ścieżki, np.:

```text
/srv/dev-disk-by-uuid-.../kuklenas/Music_Sorted
/srv/dev-disk-by-uuid-.../DockerConfig/dodajmuzyke/downloads
```

### 3. Dostosuj `docker-compose.yml`

Najważniejsze są wolumeny:

```yaml
volumes:
  - /REALNA/SCIEZKA/Music_Sorted:/music
  - /REALNA/SCIEZKA/DockerConfig/dodajmuzyke/downloads:/downloads
```

Navidrome powinien czytać ten sam katalog muzyki, najlepiej read-only:

```yaml
volumes:
  - /REALNA/SCIEZKA/Music_Sorted:/music:ro
```

### 4. Opcjonalna konfiguracja `.env`

```bash
cp .env.example .env
nano .env
```

Najważniejsze zmienne:

```bash
DODAJMUZYKE_MUSIC_DIR=/music
DODAJMUZYKE_WORK_DIR=/downloads
DODAJMUZYKE_DATABASE_PATH=/downloads/dodajmuzyke.sqlite3
DODAJMUZYKE_PUBLIC_BASE_URL=http://dodajmuzyke.local
```

Opcjonalnie można ustawić klucz AcoustID:

```bash
DODAJMUZYKE_ACOUSTID_API_KEY=...
```

Nie commituj prawdziwych sekretów.

### 5. Uruchom

```bash
docker compose up -d --build
```

Sprawdź kontenery:

```bash
docker compose ps
```

Sprawdź healthcheck:

```bash
curl http://127.0.0.1:8087/healthz
```

Poprawny wynik zawiera m.in.:

```json
{"ok":true}
```

### 6. Aktualizacja

```bash
git pull
docker compose up -d --build
```

## Przykładowy `docker-compose.yml`

Repo zawiera gotowy `docker-compose.yml`. Minimalna usługa wygląda tak:

```yaml
services:
  dodajmuzyke:
    build: .
    image: dodajmuzyke:local
    container_name: dodajmuzyke
    restart: unless-stopped
    environment:
      DODAJMUZYKE_MUSIC_DIR: /music
      DODAJMUZYKE_WORK_DIR: /downloads
      DODAJMUZYKE_DATABASE_PATH: /downloads/dodajmuzyke.sqlite3
      DODAJMUZYKE_PUBLIC_BASE_URL: http://dodajmuzyke.local
    volumes:
      - /srv/music/Music_Sorted:/music
      - /srv/docker/dodajmuzyke/downloads:/downloads
    ports:
      - "8087:8000"
```

## Reverse proxy i lokalny DNS

Aplikacja działa bez proxy pod:

```text
http://IP_SERWERA:8087
```

Dla wygody możesz dodać lokalny DNS:

```text
dodajmuzyke.local -> IP_SERWERA
```

Jeżeli używasz Caddy/nginx/Traefik, skieruj host `dodajmuzyke.local` na:

```text
http://dodajmuzyke:8000
```

albo na hostowy port:

```text
http://IP_SERWERA:8087
```

W repo jest przykładowy plik:

```text
deploy/Caddyfile
```

## Jak działa automatyczne rozpoznawanie metadanych

Kolejność źródeł:

1. Strukturalne dane `yt-dlp`, jeśli są dostępne.
2. Opis YouTube, przede wszystkim blok:

```text
Muzyka
1 utwór

Tytuł
Artysta
Album
```

3. Linie opisowe, np. `Artist:`, `Title:`, `Album:`, `Twórcy:`.
4. Tytuł filmu YouTube jako fallback.
5. Weryfikacja kolejności `artist/title` po znanych artystach z katalogów `/music/<Artist>`.
6. MusicBrainz/AcoustID/fpcalc.
7. Ręczna korekta w kolejce.

Przykład:

```text
"Veganka" - Lej Mi Pół (oficjalna taśma VHS)
```

Jeśli `Lej Mi Pół` istnieje jako znany artysta albo blok `Muzyka` podaje dane, aplikacja ustali:

```text
artist = Lej Mi Pół
title  = Veganka
album  = Wszystkiego Najlepszego Marian
```

## Blokada duplikatów

Linki:

```text
https://youtu.be/22oNZe1H2qI?si=abc
https://youtu.be/22oNZe1H2qI?si=xyz
https://www.youtube.com/watch?v=22oNZe1H2qI
```

są traktowane jako ten sam utwór:

```text
youtube:22oNZe1H2qI
```

Jeśli zadanie już istnieje i nie jest `failed/deleted`, aplikacja nie pobierze utworu drugi raz.

## API

```text
GET    /healthz
GET    /api/search?q=...
POST   /api/youtube             {"query":"URL albo fraza"}
POST   /api/upload              multipart file=...
GET    /api/jobs
GET    /api/jobs/{id}
DELETE /api/jobs/{id}
POST   /api/jobs/{id}/manual    {"artist":"...","title":"...","album":"...","year":"...","track":"..."}
```

## Wymagane narzędzia w kontenerze

Dockerfile instaluje:

- `ffmpeg`,
- `yt-dlp` z `requirements.txt`,
- `fpcalc` / `libchromaprint-tools`,
- `unzip`,
- `unrar-free`,
- `nodejs` jako JavaScript runtime dla trudniejszych przypadków YouTube/yt-dlp.

## Development lokalny

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
DODAJMUZYKE_MUSIC_DIR=/tmp/dodajmuzyke-music \
DODAJMUZYKE_WORK_DIR=/tmp/dodajmuzyke-work \
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Testy:

```bash
pytest -q
```

## Troubleshooting

### `Szukaj` trwa długo

Wyszukiwanie YouTube idzie przez `yt-dlp` i może trwać kilkanaście-kilkadziesiąt sekund. UI pokazuje wtedy `Szukam...`.

### YouTube zwraca 403 / Precondition failed / Requested format unavailable

Najpierw zaktualizuj `yt-dlp` i przebuduj obraz:

```bash
docker compose build --no-cache dodajmuzyke
docker compose up -d
```

### Navidrome nie widzi nowych plików

Sprawdź, czy Navidrome i `dodajmuzyke` używają tego samego hostowego katalogu muzyki. Następnie wymuś skan w Navidrome albo zrestartuj kontener Navidrome.

### Utwór trafił do `_Unmatched`

Otwórz `Kolejka`, kliknij wiersz zadania, uzupełnij metadane i kliknij `Zapisz ręcznie`.

## Bezpieczeństwo

- Nie commituj `.env` ani kluczy API.
- Aplikacja ma zapis do `/music`, więc montuj dokładnie katalog biblioteki, który chcesz obsługiwać.
- Jeżeli wystawiasz aplikację poza LAN/VPN, dodaj uwierzytelnianie na reverse proxy.

## Licencja

Projekt prywatny/homelabowy. Dodaj licencję, jeśli repo ma być publicznie używane przez inne osoby.
