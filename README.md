# magic-piano

Автоматический плеер для игр с раскладкой Virtual Piano (Roblox Magic Piano,
virtualpiano.net и клоны). Читает `.song` или `.mid` и отправляет нажатия
клавиш в активное окно через `/dev/uinput`.

Проверено в Sober на Hyprland/Wayland: гамма и «Twinkle» играют правильно.

## Что уже работает

- Виртуальная клавиатура через uinput: Wayland/Hyprland, Sober. Без
  сторонних Python-пакетов.
- Раскладка «белая клавиша = символ, чёрная = Shift + символ слева».
- Песни в текстовом формате и **MIDI** (форматы 0/1): tempo map, running
  status, note-on с velocity 0, несколько дорожек, авто-подбор октавы.
- **Аккорды**: одновременные ноты, удержание, счётчик Shift.
- CLI с сухим прогоном и точным планировщиком (~1 мс).

## Требования

- Linux с доступом на запись в `/dev/uinput` (у h1chan уже есть через ACL);
- Python 3.10+, без сторонних пакетов;
- активная раскладка US (проверить: `hyprctl devices | grep 'active keymap'`).

## Быстрый старт

```bash
cd ~/Projects/magic-piano

python3 -m magic_piano.play --list-layout              # нота -> клавиша
python3 -m magic_piano.play songs/scale.song --dry-run # таймлайн без отправки
python3 -m magic_piano.play songs/scale.song           # 3 с на фокус в игре
```

MIDI-демо (Бетховен, «Ода к радости», мелодия + аккорды):

```bash
python3 tools/make_demo_midi.py
python3 -m magic_piano.play songs/ode_to_joy.mid --dry-run
python3 -m magic_piano.play songs/ode_to_joy.mid --speed 0.9
```

Свой файл: положи `.mid` в `songs/` и запусти

```bash
python3 -m magic_piano.play songs/moonlight.mid --info
python3 -m magic_piano.play songs/moonlight.mid --dry-run
python3 -m magic_piano.play songs/moonlight.mid
```

Опции: `--bpm`, `--gate`, `--speed`, `--transpose <полутона>`, `--no-fit`,
`--tracks 1,2`, `--drums`, `--start-note C3`, `--countdown 5`.

## Формат песни

```
bpm 100
1 1 5 5 6 6 5     // один токен = один бит
4 4 3 3 2 2 1
```

Токен — клавиша Virtual Piano (`1`, `q`, `Q`, `!`) или нота (`C4`, `D#4`).
`|` и `//`-комментарии игнорируются. Комментарии именно `//`, потому что `#`
входит в имена диезов.

## Раскладка

Первая белая клавиша по умолчанию — C3 (MIDI 48). Белые клавиши идут по
строке `1234567890qwertyuiopasdfghjklzxcvbnm`, чёрная — Shift плюс белая
клавиша слева.

```
C3=1  C#3=Shift+1  D3=2  D#3=Shift+2  E3=3  F3=4  F#3=Shift+4  G3=5 ...
C4=8  C#4=Shift+8  D4=9  D#4=Shift+9  E4=0  F4=q  F#4=Q  G4=w ...
```

## Ограничение аккордов

`q` и `Q` — разные ноты одной физической клавиши. Если в аккорде нужны обе,
сыграть их одновременно нельзя; вторая нота пропускается. Это ограничение
раскладки, а не плеера.

## Тесты

```bash
python3 -m unittest discover -s tests -v   # 30 тестов
```

## Дорожная карта

1. ~~MIDI-импорт и аккорды~~ — готово.
2. Определение своей раскладки калибратором (для нестандартных игр).
3. Улучшенная аранжировка: отсечение далёких басов, приоритет мелодии при
   нехватке клавиш, использование кнопки Sustain.
4. Прогресс-бар и горячая клавиша остановки.

## Оговорка

Автоматизация нарушает правила Roblox и конкретной игры; аккаунт может быть
заблокирован. Пользуйся на свой риск и не мешай другим игрокам.
