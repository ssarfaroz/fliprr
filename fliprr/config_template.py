TEMPLATE = """\
# Настройки fliprr. Строки с # — комментарии.
# Файл ищется так: $FLIPRR_CONFIG → ./fliprr.toml → этот файл.

language = "ru"            # язык фраз самого ассистента: ru | en

[claude_code]
# Папка проекта, в которой работает Claude Code («Клод Код, …»).
cwd = "{cwd}"
# Проекты, между которыми можно переключаться голосом: «Клод Код, проект блог».
# [claude_code.projects]
# блог = "~/code/blog"
# fliprr = "~/code/fliprr"

permission_mode = "default"   # default — спрашивать голосом перед командами и правками
                              # acceptEdits — правки файлов без вопросов (команды — с вопросом)
ask_timeout_s = 60            # сколько ждать ответа «да/нет»
speak = "all"                 # all — озвучивать ход работы и итог; final — только итог
announce_tools = false        # озвучивать каждый инструмент («Выполняю команду…»)
continue_last = false         # при запуске продолжать прошлую сессию в этой папке
# model = "sonnet"            # пусто — модель по умолчанию из Claude Code
# auto_allow = ["Bash(git status:*)", "Bash(npm test:*)"]   # разрешено без вопросов

[chat]
# «Клод, …» — обычный разговор с Claude (без доступа к файлам).
effort = "low"                # low — быстрые ответы голосом
web = true                    # разрешить поиск в интернете
resume = true                 # после перезапуска продолжать последний чат
# model = ""
# instructions = "Обращайся ко мне на ты."

[wake]
default_target = "chat"       # кого зовёт просто «Клод»: chat или code
followup_s = 8                # после ответа можно продолжать без «Клод» столько секунд
listen_timeout_s = 8          # после одиночного «Клод!» ждать просьбу столько секунд
max_prefix_words = 3          # «Клод» должен быть среди первых N слов фразы
# extra_claude_words = ["клоди"]   # если распознавание пишет имя по-своему

[stt]
engine = "whisper"            # whisper — локально (faster-whisper); openai — через API
model = "small"               # tiny | base | small | medium | large-v3-turbo (лучше всего, нужен мощный ПК/GPU)
device = "auto"               # auto | cpu | cuda
language = "ru"               # "" — определять язык автоматически
beam_size = 5
# Для слабого компьютера: распознавание через Groq (быстро, есть бесплатный тариф)
# engine = "openai"
# api_base = "https://api.groq.com/openai/v1"
# api_key_env = "GROQ_API_KEY"
# api_model = "whisper-large-v3-turbo"

[tts]
engine = "edge"               # edge — голоса Microsoft (бесплатно, нужен интернет)
                              # piper — офлайн-голоса; system — голос системы; none — без звука
fallback = "system"           # запасной вариант, если основной не сработал
voice = "ru-RU-SvetlanaNeural"   # или ru-RU-DmitryNeural
voice_en = "en-US-AvaNeural"
rate = "+10%"
# piper_voice = "ru_RU-irina-medium"   # ещё: ru_RU-dmitri-medium, ru_RU-denis-medium, ru_RU-ruslan-medium

[audio]
input_device = ""             # микрофон: номер или часть названия (см. fliprr devices)
output_device = ""
input_gain = 1.0              # усиление микрофона, если говоришь издалека (например 2.0)
vad_threshold = 0.5           # чувствительность детектора речи (меньше — чувствительнее)
end_silence_ms = 900          # пауза, после которой фраза считается законченной
barge_in = true               # слушать во время ответа, чтобы работало «Клод, стоп»
earcons = true                # короткие звуковые сигналы
earcon_volume = 0.25
"""
