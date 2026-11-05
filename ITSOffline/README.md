# ITSOffline

Консольный загрузчик комплекта ИТС Offline и локальный просмотрщик в браузере.
Только стандартная библиотека Python 3. Обзор репозитория и план докачки — в корневом `README.md`.
Распакованные базы и архивы `.pack` лежат в `data/` и в git не входят.

## Сборка извлекателя ISCF

Страницы книг лежат в `Storage/Data.cab` (контейнер `ISCF`, LZX). Для распаковки нужен бинарник:

```bash
cd native/iscf_extract
cargo build --release
cp target/release/iscf_extract ../bin/   # опционально
```

Либо задайте `ITSOFFLINE_ISCF_EXTRACT=/path/to/iscf_extract`.

## Загрузка

Из каталога `ITSOffline`:

```bash
python3 -m its_offline download --all --out data
python3 -m its_offline download --kit prof,techno --out data
python3 -m its_offline download --kit medicine --database V8Doc --out data
```

Без `--all` / `--kit` в интерактивном терминале откроется меню. В пайпе без флагов — ошибка.

Каталоги: `data/packs/*.pack`, `data/library/<ИмяБазы>/` (дерево `SRC/` + `toc.json`).

## Просмотр

```bash
python3 -m its_offline serve --data data --port 8765
```

Слушает только `127.0.0.1`, открывает браузер. Слева оглавление из `toc.json`, справа страница в iframe.

## Тесты

```bash
cd ITSOffline
PYTHONPATH=. python3 -m unittest discover -s tests -v
```
