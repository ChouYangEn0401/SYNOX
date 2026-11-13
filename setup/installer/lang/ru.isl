; SYNOX installer texts, Russian (ru). Model-written translation: NEEDS NATIVE-SPEAKER REVIEW.
; Loaded after lang\en.isl, so a missing key falls back to English. Keys must match en.isl (tests/test_installer_script.py).

[LangOptions]
LanguageName=Русский (Russian)

[Messages]
SelectLanguageTitle=Язык · Language
SelectLanguageLabel=Выберите язык. Его будут использовать установщик, мастер настройки и SYNOX.
WelcomeLabel1=Добро пожаловать в SYNOX. Приятного пользования!
WelcomeLabel2=•  Небольшой помощник, который живёт на вашем компьютере. Общайтесь с ним через Telegram, Discord или веб-страницу.%n•  Приносит свой собственный Python и не трогает остальное на этом компьютере.%n•  Без пароля администратора: всё ставится в одну папку в вашей учётной записи.%n•  Начните с короткого обучения, а потом выберите нужные инструменты.
WizardSelectTasks=Что подготовить?
SelectTasksDesc=Всё уже выставлено по рекомендации.
SelectTasksLabel2=Любой пункт можно изменить позже: снова запустите установщик или откройте настройки SYNOX.
FinishedHeadingLabel=SYNOX установлен
FinishedLabel=Последний шаг: откройте мастер настройки, подключите Telegram (или Discord) и выберите ИИ. Это займёт около 3 минут. Затем пройдите короткое обучение.
ClickFinish=Нажмите «Завершить», чтобы закрыть установщик.
ConfirmUninstall=Удалить %1 сейчас?
UninstalledAll=%1 удалён.
UninstalledMost=%1 удалён.%n%nВаши настройки и данные остались в папке SYNOX, после новой установки можно продолжить с того же места.
FinishedLabelNoIcons=Последний шаг: откройте мастер настройки, подключите Telegram (или Discord) и выберите ИИ. Это займёт около 3 минут. Затем пройдите короткое обучение.

[CustomMessages]
DirNotWritable=SYNOX хранит ваши данные в этой папке, но не может сюда записывать. Выберите другое место.
FinishedClaudeSkipped=Claude Code пока пропущен (возможно, нет интернета). Его можно добавить позже на странице ИИ в мастере настройки: «Установить в один клик (PowerShell)».
IconOpen=Открыть SYNOX
IconUninstall=Удалить SYNOX
IconWizard=Мастер настройки SYNOX
LicenseFile=LICENSE
LicenseLine=Бесплатно для личного использования. Для коммерческого использования прочитайте <a id="license">лицензию AGPL-3.0</a>.
RunSetupNow=Открыть мастер настройки сейчас (рекомендуется)
StatusClaude=Устанавливается Claude Code (нужен интернет, это может занять несколько минут)…
SynoxLangCode=ru
TaskAllTools=Установить все официальные инструменты (не рекомендуется: сначала пройдите обучение, потом выберите нужное)
TaskAutostart=Запускать SYNOX при входе в систему (небольшое видимое окно, которое можно закрыть)
TaskClaude=Установить Claude Code (только если его нет; нужен интернет; ставится в вашу папку пользователя)
TaskClaudePresent=Claude Code уже установлен
TaskDesktop=Создать ярлык "SYNOX" на рабочем столе
TaskFileType=Устанавливать файлы .synoxpack двойным щелчком (с проверкой и подтверждением)
TaskStartMenu=Добавить «SYNOX» в меню «Пуск»
TypeCustom=Выборочная (выбрать папку и каждый пункт)
TypeDesc=Большинству подходит рекомендуемый вариант.
TypeLabel=Рекомендуемый вариант ставит SYNOX с собственным Python, ярлыками на рабочем столе и в меню «Пуск», установкой файлов .synoxpack двойным щелчком, запуском при входе в систему и обучением. Если на этом компьютере ещё нет Claude Code, он тоже будет установлен (нужен интернет; ставится в вашу папку пользователя). Захотите иначе — просто запустите установщик ещё раз; данные сохранятся.
TypeRecommended=Рекомендуемая (всё сделать за меня)
TypeTitle=Как установить SYNOX?
UninstallConfirmData=Точно удалить и ваши данные?%n%nВаши настройки, заметки, учёт расходов, сохранённые ключи и установленные инструменты будут удалены. Это нельзя отменить.
UninstallDeleteData=Удалить и мои данные
UninstallDeleteDataNote=Это нельзя отменить. Мы спросим ещё раз.
UninstallHeading=Удалить SYNOX?
UninstallKeeps=Останется: ваши настройки, заметки, учёт расходов, сохранённые ключи и установленные инструменты. Они остаются в папке SYNOX, после новой установки можно продолжить.
UninstallRemoves=Будет удалено: программа SYNOX, её собственный Python, ярлыки, запуск при входе в систему и установка .synoxpack двойным щелчком.
UninstallTitle=Удаление SYNOX
UninstallUntouched=Другие Python, Conda и Claude Code на этом компьютере не затрагиваются.
