# onec_its_downloader

Локальная копия материалов ИТС. Офлайн-комплект скачивается по официальному манифесту, книги только с сайта — прямыми HTTP-запросами. Читать их можно в браузере на своей машине.

## Что лежит в репозитории

Код и тесты — в `ITSOffline/`, только стандартная библиотека Python 3.10.

- `its_offline` — загрузчик офлайн-комплекта. Берёт `https://its.1c.ru/itsoffline/update/latest.xml` и пакеты с fserver.1c.ru, распаковывает их в `data/library/<ИмяБазы>/`.
- `native/iscf_extract` — программа на Rust. Страницы книг лежат в `Storage/Data.cab` (контейнер ISCF, сжатие LZX). Без этого бинарника новая распаковка офлайн-пакета не начнётся. Ищется `ITSOffline/bin/iscf_extract`, затем `native/iscf_extract/target/release/iscf_extract`. Свой путь задаётся переменной `ITSOFFLINE_ISCF_EXTRACT`.
- `its_web` — загрузка HTML с its.1c.ru по логину ИТС: оглавление, главы, картинки и общие стили. Так добираются материалы, которых нет в офлайн-комплекте: ERP, свежая платформа, книги и статьи.
- `static` — страница просмотрщика: слева оглавление из `toc.json`, справа текст.
- `tests` — `unittest`.
- `missing.md` — сверка меню its.1c.ru с `data/library` на 4 ноября 2026. 340 баз ещё не скачаны. Код в первой колонке передаётся в `--db`.

В git лежит распакованный `data/library`. Не входит только `Staff1CBud/Storage/Data.cab`: это 1,5 ГБ, а GitHub не принимает файл больше 100 МБ. Сам каталог `Staff1CBud` без этого контейнера в репозитории есть.

Архивы `.pack` после распаковки для чтения не нужны, в репозиторий их не кладём.

У шести офлайн-баз страниц HTML нет: `Common`, `ItsCl`, `Staff1CBud`, `newsclar`, `newscomm`, `newsprac`. У пяти из них распаковка остановилась на `Storage/Data.cab`.

## Как запустить

Просмотр того, что уже лежит в `data/library`:

```bash
cd ITSOffline
python3 -m its_offline serve --data data --port 8765
```

Откроется `http://127.0.0.1:8765/`. Слушает только этот компьютер. Если порт занят, укажите другой.

Офлайн-комплект. Пакеты занимают около 18 ГБ, для распаковки нужен `iscf_extract`.

```bash
cd ITSOffline/native/iscf_extract
cargo build --release

cd ../..
python3 -m its_offline download --all --out data
```

Комплект или одна база: `--kit prof,techno` (ещё `budget-prof`, `budget`, `medicine`) и `--database V8Doc`. В терминале без флагов откроется меню. Если Python с python.org ругается на сертификат:

```bash
SSL_CERT_FILE=/etc/ssl/cert.pem python3 -m its_offline download --all --out data
```

Базы с сайта, которых нет в офлайн-комплекте. Логин и пароль в репозиторий не входят: переменные `ITS_USERNAME` и `ITS_PASSWORD` либо файл `--env` с ключами `USERNAME` и `PASSWORD`. Если рядом с репозиторием есть `its_scrapper/.env`, он подхватывается сам.

```bash
cd ITSOffline
python3 -m its_web download --db bp8doc --out data --delay 0.25
```

Несколько баз — несколько `--db`. Пауза между запросами по умолчанию 0,25 с. Повторный запуск докачивает только недостающее. `--limit N` берёт первые N файлов, удобно для проверки.

Тесты:

```bash
cd ITSOffline
python3 -m unittest discover -s tests -v
```

## Следующие шаги

Докачивать `missing.md` через `its_web`, по одной базе или коротким списком. Пока идёт закачка, второй вход не делать: новая сессия сбрасывает текущую. База вне договора отвечает «Доступ к данному материалу ограничен», такой файл в оглавление не попадает.

Сначала типовые руководства: `bp8doc`, `hrmdoc`, `zupcorpdoc`, `erp26doc`, `erp25ltsdoc`, `ka26doc`, `ka25ltsdoc`, `ut116doc`, `ut115ltsdoc`, `utbase115doc`, `unfdoc`, `retail30doc`, `retaildoc`, `uhdoc33`, `uherpdoc33`, `bgudoc`, `statehrmdoc`, `doc30`, `docprof30`, `crm31`, `cabinetdoc`. Дальше книги Академии ERP и отраслевые руководства под свои конфигурации.

Отдельно разобрать шесть пустых офлайн-каталогов: контейнер ISCF у них не читается.

Новые базы из `data/library` отправлять частями: один большой push GitHub обрывает по таймауту. Каталог `data/packs` и файлы больше 100 МБ в git не добавлять.
