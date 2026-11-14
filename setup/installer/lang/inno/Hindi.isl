; *** Inno Setup 6 built-in messages, Hindi ***
;
; SYNOX's own translation, written for the SYNOX installer (not a copy of any third-party translation file).
; Same keys as Default.isl of Inno Setup 6.7.4; scripts/installer_ci.py check-iss keeps them complete.
; Inno Setup adds a period to some messages by itself: do not add one where English has none.
; Access keys stay Latin letters in brackets, e.g. "अगला(&N) >", so Alt+N works on any keyboard.
; Loaded first for hi; lang\en.isl and lang\hi.isl (SYNOX's own texts) come after it.

[LangOptions]
LanguageName=हिन्दी (Hindi)
LanguageID=$0439
; Hindi has no ANSI code page: zero, and this file is UTF-8 only.
LanguageCodePage=0

[Messages]

; *** Application titles
SetupAppTitle=सेटअप
SetupWindowTitle=सेटअप - %1
UninstallAppTitle=अनइंस्टॉल
UninstallAppFullTitle=%1 अनइंस्टॉल

; *** Misc. common
InformationTitle=जानकारी
ConfirmTitle=पुष्टि करें
ErrorTitle=त्रुटि

; *** SetupLdr messages
SetupLdrStartupMessage=यह %1 इंस्टॉल करेगा। क्या आप जारी रखना चाहते हैं?
LdrCannotCreateTemp=अस्थायी फ़ाइल नहीं बन सकी। सेटअप रोक दिया गया
LdrCannotExecTemp=अस्थायी फ़ोल्डर की फ़ाइल नहीं चल सकी। सेटअप रोक दिया गया
HelpTextNote=

; *** Startup error messages
LastErrorMessage=%1.%n%nत्रुटि %2: %3
SetupFileMissing=इंस्टॉलेशन फ़ोल्डर में फ़ाइल %1 नहीं है। कृपया समस्या ठीक करें या प्रोग्राम की नई कॉपी लें।
SetupFileCorrupt=सेटअप फ़ाइलें खराब हो गई हैं। कृपया प्रोग्राम की नई कॉपी लें।
SetupFileCorruptOrWrongVer=सेटअप फ़ाइलें खराब हैं, या सेटअप के इस संस्करण के साथ काम नहीं करतीं। कृपया समस्या ठीक करें या प्रोग्राम की नई कॉपी लें।
InvalidParameter=कमांड लाइन में एक अमान्य पैरामीटर दिया गया:%n%n%1
SetupAlreadyRunning=सेटअप पहले से चल रहा है।
WindowsVersionNotSupported=यह प्रोग्राम आपके कंप्यूटर के Windows संस्करण पर काम नहीं करता।
WindowsServicePackRequired=इस प्रोग्राम के लिए %1 Service Pack %2 या उससे नया चाहिए।
NotOnThisPlatform=यह प्रोग्राम %1 पर नहीं चलेगा।
OnlyOnThisPlatform=यह प्रोग्राम केवल %1 पर चलना चाहिए।
OnlyOnTheseArchitectures=यह प्रोग्राम केवल इन प्रोसेसर आर्किटेक्चर के लिए बने Windows पर इंस्टॉल हो सकता है:%n%n%1
WinVersionTooLowError=इस प्रोग्राम के लिए %1 संस्करण %2 या उससे नया चाहिए।
WinVersionTooHighError=यह प्रोग्राम %1 संस्करण %2 या उससे नए पर इंस्टॉल नहीं हो सकता।
AdminPrivilegesRequired=यह प्रोग्राम इंस्टॉल करने के लिए आपको व्यवस्थापक (administrator) के रूप में लॉग इन होना चाहिए।
PowerUserPrivilegesRequired=यह प्रोग्राम इंस्टॉल करने के लिए आपको व्यवस्थापक या Power Users समूह के सदस्य के रूप में लॉग इन होना चाहिए।
SetupAppRunningError=सेटअप ने पाया कि %1 अभी चल रहा है।%n%nकृपया इसे पूरी तरह बंद करें, फिर जारी रखने के लिए ठीक दबाएँ, या बाहर निकलने के लिए रद्द करें दबाएँ।
UninstallAppRunningError=अनइंस्टॉल ने पाया कि %1 अभी चल रहा है।%n%nकृपया इसे पूरी तरह बंद करें, फिर जारी रखने के लिए ठीक दबाएँ, या बाहर निकलने के लिए रद्द करें दबाएँ।

; *** Startup questions
PrivilegesRequiredOverrideTitle=सेटअप इंस्टॉल मोड चुनें
PrivilegesRequiredOverrideInstruction=इंस्टॉल मोड चुनें
PrivilegesRequiredOverrideText1=%1 सभी उपयोगकर्ताओं के लिए (व्यवस्थापक अधिकार चाहिए) या केवल आपके लिए इंस्टॉल हो सकता है।
PrivilegesRequiredOverrideText2=%1 केवल आपके लिए या सभी उपयोगकर्ताओं के लिए (व्यवस्थापक अधिकार चाहिए) इंस्टॉल हो सकता है।
PrivilegesRequiredOverrideAllUsers=सभी उपयोगकर्ताओं के लिए इंस्टॉल करें(&A)
PrivilegesRequiredOverrideAllUsersRecommended=सभी उपयोगकर्ताओं के लिए इंस्टॉल करें (सुझाया गया)(&A)
PrivilegesRequiredOverrideCurrentUser=केवल मेरे लिए इंस्टॉल करें(&M)
PrivilegesRequiredOverrideCurrentUserRecommended=केवल मेरे लिए इंस्टॉल करें (सुझाया गया)(&M)

; *** Misc. errors
ErrorCreatingDir=सेटअप फ़ोल्डर "%1" नहीं बना सका
ErrorTooManyFilesInDir=फ़ोल्डर "%1" में बहुत अधिक फ़ाइलें हैं, इसलिए उसमें नई फ़ाइल नहीं बन सकी

; *** Setup common messages
ExitSetupTitle=सेटअप से बाहर निकलें
ExitSetupMessage=सेटअप पूरा नहीं हुआ है। अगर आप अभी बाहर निकलते हैं, तो प्रोग्राम इंस्टॉल नहीं होगा।%n%nइंस्टॉलेशन पूरा करने के लिए आप बाद में सेटअप फिर से चला सकते हैं।%n%nक्या सेटअप से बाहर निकलें?
AboutSetupMenuItem=सेटअप के बारे में(&A)...
AboutSetupTitle=सेटअप के बारे में
AboutSetupMessage=%1 संस्करण %2%n%3%n%n%1 का होम पेज:%n%4
AboutSetupNote=
TranslatorNote=

; *** Buttons
ButtonBack=< पीछे(&B)
ButtonNext=अगला(&N) >
ButtonInstall=इंस्टॉल करें(&I)
ButtonOK=ठीक है
ButtonCancel=रद्द करें
ButtonYes=हाँ(&Y)
ButtonYesToAll=सभी के लिए हाँ(&A)
ButtonNo=नहीं(&N)
ButtonNoToAll=सभी के लिए नहीं(&O)
ButtonFinish=समाप्त(&F)
ButtonBrowse=ब्राउज़ करें(&B)...
ButtonWizardBrowse=ब्राउज़ करें(&R)...
ButtonNewFolder=नया फ़ोल्डर बनाएँ(&M)

; *** "Select Language" dialog messages
SelectLanguageTitle=सेटअप की भाषा चुनें
SelectLanguageLabel=इंस्टॉलेशन के दौरान उपयोग होने वाली भाषा चुनें।

; *** Common wizard text
ClickNext=जारी रखने के लिए अगला दबाएँ, या सेटअप से बाहर निकलने के लिए रद्द करें दबाएँ।
BeveledLabel=
BrowseDialogTitle=फ़ोल्डर ब्राउज़ करें
BrowseDialogLabel=नीचे की सूची में से एक फ़ोल्डर चुनें, फिर ठीक है दबाएँ।
NewFolderName=नया फ़ोल्डर

; *** "Welcome" wizard page
WelcomeLabel1=[name] सेटअप विज़ार्ड में आपका स्वागत है
WelcomeLabel2=यह आपके कंप्यूटर पर [name/ver] इंस्टॉल करेगा।%n%nआगे बढ़ने से पहले बाकी सभी ऐप्लिकेशन बंद कर देना अच्छा रहेगा।

; *** "Password" wizard page
WizardPassword=पासवर्ड
PasswordLabel1=यह इंस्टॉलेशन पासवर्ड से सुरक्षित है।
PasswordLabel3=कृपया पासवर्ड डालें, फिर जारी रखने के लिए अगला दबाएँ। पासवर्ड में छोटे-बड़े अक्षरों का अंतर मायने रखता है।
PasswordEditLabel=पासवर्ड(&P):
IncorrectPassword=आपका डाला गया पासवर्ड सही नहीं है। कृपया फिर से कोशिश करें।

; *** "License Agreement" wizard page
WizardLicense=लाइसेंस अनुबंध
LicenseLabel=आगे बढ़ने से पहले कृपया नीचे दी गई ज़रूरी जानकारी पढ़ें।
LicenseLabel3=कृपया नीचे दिया गया लाइसेंस अनुबंध पढ़ें। इंस्टॉलेशन जारी रखने से पहले आपको इसकी शर्तें स्वीकार करनी होंगी।
LicenseAccepted=मैं अनुबंध स्वीकार करता/करती हूँ(&A)
LicenseNotAccepted=मैं अनुबंध स्वीकार नहीं करता/करती(&D)

; *** "Information" wizard pages
WizardInfoBefore=जानकारी
InfoBeforeLabel=आगे बढ़ने से पहले कृपया नीचे दी गई ज़रूरी जानकारी पढ़ें।
InfoBeforeClickLabel=जब आप सेटअप जारी रखने के लिए तैयार हों, तो अगला दबाएँ।
WizardInfoAfter=जानकारी
InfoAfterLabel=आगे बढ़ने से पहले कृपया नीचे दी गई ज़रूरी जानकारी पढ़ें।
InfoAfterClickLabel=जब आप सेटअप जारी रखने के लिए तैयार हों, तो अगला दबाएँ।

; *** "User Information" wizard page
WizardUserInfo=उपयोगकर्ता की जानकारी
UserInfoDesc=कृपया अपनी जानकारी डालें।
UserInfoName=उपयोगकर्ता नाम(&U):
UserInfoOrg=संगठन(&O):
UserInfoSerial=सीरियल नंबर(&S):
UserInfoNameRequired=आपको एक नाम डालना होगा।

; *** "Select Destination Location" wizard page
WizardSelectDir=इंस्टॉल करने की जगह चुनें
SelectDirDesc=[name] कहाँ इंस्टॉल किया जाए?
SelectDirLabel3=सेटअप [name] को नीचे दिए गए फ़ोल्डर में इंस्टॉल करेगा।
SelectDirBrowseLabel=जारी रखने के लिए अगला दबाएँ। कोई दूसरा फ़ोल्डर चुनना हो, तो ब्राउज़ करें दबाएँ।
DiskSpaceGBLabel=कम से कम [gb] GB खाली डिस्क स्पेस चाहिए।
DiskSpaceMBLabel=कम से कम [mb] MB खाली डिस्क स्पेस चाहिए।
CannotInstallToNetworkDrive=सेटअप नेटवर्क ड्राइव पर इंस्टॉल नहीं कर सकता।
CannotInstallToUNCPath=सेटअप UNC पथ पर इंस्टॉल नहीं कर सकता।
InvalidPath=आपको ड्राइव अक्षर सहित पूरा पथ डालना होगा, जैसे:%n%nC:\APP%n%nया इस रूप में UNC पथ:%n%n\\server\share
InvalidDrive=आपकी चुनी गई ड्राइव या UNC शेयर मौजूद नहीं है या उस तक पहुँच नहीं है। कृपया कोई दूसरी चुनें।
DiskSpaceWarningTitle=डिस्क में पर्याप्त जगह नहीं
DiskSpaceWarning=इंस्टॉल करने के लिए सेटअप को कम से कम %1 KB खाली जगह चाहिए, लेकिन चुनी गई ड्राइव में केवल %2 KB उपलब्ध है।%n%nक्या आप फिर भी जारी रखना चाहते हैं?
DirNameTooLong=फ़ोल्डर का नाम या पथ बहुत लंबा है।
InvalidDirName=फ़ोल्डर का नाम मान्य नहीं है।
BadDirName32=फ़ोल्डर के नाम में ये अक्षर नहीं हो सकते:%n%n%1
DirExistsTitle=फ़ोल्डर पहले से है
DirExists=फ़ोल्डर:%n%n%1%n%nपहले से मौजूद है। क्या आप फिर भी उसी फ़ोल्डर में इंस्टॉल करना चाहते हैं?
DirDoesntExistTitle=फ़ोल्डर मौजूद नहीं है
DirDoesntExist=फ़ोल्डर:%n%n%1%n%nमौजूद नहीं है। क्या यह फ़ोल्डर बना दिया जाए?

; *** "Select Components" wizard page
WizardSelectComponents=कॉम्पोनेंट चुनें
SelectComponentsDesc=कौन-से कॉम्पोनेंट इंस्टॉल किए जाएँ?
SelectComponentsLabel2=जो कॉम्पोनेंट इंस्टॉल करने हैं उन्हें चुनें, और जो नहीं करने उनका निशान हटा दें। तैयार होने पर अगला दबाएँ।
FullInstallation=पूरा इंस्टॉलेशन
CompactInstallation=संक्षिप्त इंस्टॉलेशन
CustomInstallation=कस्टम इंस्टॉलेशन
NoUninstallWarningTitle=कॉम्पोनेंट पहले से हैं
NoUninstallWarning=सेटअप ने पाया कि ये कॉम्पोनेंट आपके कंप्यूटर पर पहले से इंस्टॉल हैं:%n%n%1%n%nइनका निशान हटाने से ये अनइंस्टॉल नहीं होंगे।%n%nक्या आप फिर भी जारी रखना चाहते हैं?
ComponentSize1=%1 KB
ComponentSize2=%1 MB
ComponentsDiskSpaceGBLabel=मौजूदा चुनाव के लिए कम से कम [gb] GB डिस्क स्पेस चाहिए।
ComponentsDiskSpaceMBLabel=मौजूदा चुनाव के लिए कम से कम [mb] MB डिस्क स्पेस चाहिए।

; *** "Select Additional Tasks" wizard page
WizardSelectTasks=अतिरिक्त कार्य चुनें
SelectTasksDesc=कौन-से अतिरिक्त कार्य किए जाएँ?
SelectTasksLabel2=[name] इंस्टॉल करते समय सेटअप जो अतिरिक्त कार्य करे, उन्हें चुनें, फिर अगला दबाएँ।

; *** "Select Start Menu Folder" wizard page
WizardSelectProgramGroup=स्टार्ट मेनू फ़ोल्डर चुनें
SelectStartMenuFolderDesc=सेटअप प्रोग्राम के शॉर्टकट कहाँ रखे?
SelectStartMenuFolderLabel3=सेटअप प्रोग्राम के शॉर्टकट नीचे दिए गए स्टार्ट मेनू फ़ोल्डर में बनाएगा।
SelectStartMenuFolderBrowseLabel=जारी रखने के लिए अगला दबाएँ। कोई दूसरा फ़ोल्डर चुनना हो, तो ब्राउज़ करें दबाएँ।
MustEnterGroupName=आपको फ़ोल्डर का नाम डालना होगा।
GroupNameTooLong=फ़ोल्डर का नाम या पथ बहुत लंबा है।
InvalidGroupName=फ़ोल्डर का नाम मान्य नहीं है।
BadGroupName=फ़ोल्डर के नाम में ये अक्षर नहीं हो सकते:%n%n%1
NoProgramGroupCheck2=स्टार्ट मेनू फ़ोल्डर न बनाएँ(&D)

; *** "Ready to Install" wizard page
WizardReady=इंस्टॉल करने के लिए तैयार
ReadyLabel1=सेटअप अब आपके कंप्यूटर पर [name] इंस्टॉल करने के लिए तैयार है।
ReadyLabel2a=इंस्टॉलेशन जारी रखने के लिए इंस्टॉल करें दबाएँ, या कोई सेटिंग देखनी या बदलनी हो तो पीछे दबाएँ।
ReadyLabel2b=इंस्टॉलेशन जारी रखने के लिए इंस्टॉल करें दबाएँ।
ReadyMemoUserInfo=उपयोगकर्ता की जानकारी:
ReadyMemoDir=इंस्टॉल करने की जगह:
ReadyMemoType=सेटअप का प्रकार:
ReadyMemoComponents=चुने गए कॉम्पोनेंट:
ReadyMemoGroup=स्टार्ट मेनू फ़ोल्डर:
ReadyMemoTasks=अतिरिक्त कार्य:

; *** TDownloadWizardPage wizard page and DownloadTemporaryFile
DownloadingLabel2=फ़ाइलें डाउनलोड हो रही हैं...
ButtonStopDownload=डाउनलोड रोकें(&S)
StopDownload=क्या आप सच में डाउनलोड रोकना चाहते हैं?
ErrorDownloadAborted=डाउनलोड रोक दिया गया
ErrorDownloadFailed=डाउनलोड नहीं हो सका: %1 %2
ErrorDownloadSizeFailed=आकार पता नहीं चल सका: %1 %2
ErrorProgress=प्रगति गलत है: %2 में से %1
ErrorFileSize=फ़ाइल का आकार गलत है: अपेक्षित %1, मिला %2

; *** TExtractionWizardPage wizard page and ExtractArchive
ExtractingLabel=फ़ाइलें निकाली जा रही हैं...
ButtonStopExtraction=निकालना रोकें(&S)
StopExtraction=क्या आप सच में फ़ाइलें निकालना रोकना चाहते हैं?
ErrorExtractionAborted=फ़ाइलें निकालना रोक दिया गया
ErrorExtractionFailed=फ़ाइलें नहीं निकल सकीं: %1

; *** Archive extraction failure details
ArchiveIncorrectPassword=पासवर्ड गलत है
ArchiveIsCorrupted=आर्काइव खराब है
ArchiveUnsupportedFormat=यह आर्काइव फ़ॉर्मेट समर्थित नहीं है

; *** "Preparing to Install" wizard page
WizardPreparing=इंस्टॉल करने की तैयारी
PreparingDesc=सेटअप आपके कंप्यूटर पर [name] इंस्टॉल करने की तैयारी कर रहा है।
PreviousInstallNotCompleted=पिछले किसी प्रोग्राम का इंस्टॉल या हटाना पूरा नहीं हुआ। उसे पूरा करने के लिए आपको कंप्यूटर रीस्टार्ट करना होगा।%n%nकंप्यूटर रीस्टार्ट करने के बाद, [name] का इंस्टॉलेशन पूरा करने के लिए सेटअप फिर से चलाएँ।
CannotContinue=सेटअप जारी नहीं रख सकता। बाहर निकलने के लिए कृपया रद्द करें दबाएँ।
ApplicationsFound=ये ऐप्लिकेशन उन फ़ाइलों का उपयोग कर रहे हैं जिन्हें सेटअप को अपडेट करना है। अच्छा होगा कि आप सेटअप को इन्हें अपने-आप बंद करने दें।
ApplicationsFound2=ये ऐप्लिकेशन उन फ़ाइलों का उपयोग कर रहे हैं जिन्हें सेटअप को अपडेट करना है। अच्छा होगा कि आप सेटअप को इन्हें अपने-आप बंद करने दें। इंस्टॉलेशन पूरा होने के बाद सेटअप इन्हें फिर से शुरू करने की कोशिश करेगा।
CloseApplications=ऐप्लिकेशन अपने-आप बंद करें(&A)
DontCloseApplications=ऐप्लिकेशन बंद न करें(&D)
ErrorCloseApplications=सेटअप सभी ऐप्लिकेशन अपने-आप बंद नहीं कर सका। आगे बढ़ने से पहले उन सभी ऐप्लिकेशन को बंद कर दें जो अपडेट होने वाली फ़ाइलों का उपयोग कर रहे हैं।
PrepareToInstallNeedsRestart=सेटअप को आपका कंप्यूटर रीस्टार्ट करना होगा। रीस्टार्ट के बाद, [name] का इंस्टॉलेशन पूरा करने के लिए सेटअप फिर से चलाएँ।%n%nक्या आप अभी रीस्टार्ट करना चाहते हैं?

; *** "Installing" wizard page
WizardInstalling=इंस्टॉल हो रहा है
InstallingLabel=कृपया प्रतीक्षा करें, सेटअप आपके कंप्यूटर पर [name] इंस्टॉल कर रहा है।

; *** "Setup Completed" wizard page
FinishedHeadingLabel=[name] सेटअप विज़ार्ड पूरा हो रहा है
FinishedLabelNoIcons=सेटअप ने आपके कंप्यूटर पर [name] इंस्टॉल कर दिया है।
FinishedLabel=सेटअप ने आपके कंप्यूटर पर [name] इंस्टॉल कर दिया है। इसे इंस्टॉल किए गए शॉर्टकट से खोला जा सकता है।
ClickFinish=सेटअप से बाहर निकलने के लिए समाप्त दबाएँ।
FinishedRestartLabel=[name] का इंस्टॉलेशन पूरा करने के लिए सेटअप को आपका कंप्यूटर रीस्टार्ट करना होगा। क्या आप अभी रीस्टार्ट करना चाहते हैं?
FinishedRestartMessage=[name] का इंस्टॉलेशन पूरा करने के लिए सेटअप को आपका कंप्यूटर रीस्टार्ट करना होगा।%n%nक्या आप अभी रीस्टार्ट करना चाहते हैं?
ShowReadmeCheck=हाँ, मैं README फ़ाइल देखना चाहता/चाहती हूँ
YesRadio=हाँ, कंप्यूटर अभी रीस्टार्ट करें(&Y)
NoRadio=नहीं, मैं कंप्यूटर बाद में रीस्टार्ट करूँगा/करूँगी(&N)
RunEntryExec=%1 चलाएँ
RunEntryShellExec=%1 देखें

; *** "Setup Needs the Next Disk" stuff
ChangeDiskTitle=सेटअप को अगली डिस्क चाहिए
SelectDiskLabel2=कृपया डिस्क %1 डालें और ठीक है दबाएँ।%n%nअगर इस डिस्क की फ़ाइलें नीचे दिखाए गए फ़ोल्डर के अलावा किसी और फ़ोल्डर में हैं, तो सही पथ डालें या ब्राउज़ करें दबाएँ।
PathLabel=पथ(&P):
FileNotInDir2=फ़ाइल "%1" "%2" में नहीं मिली। कृपया सही डिस्क डालें या कोई दूसरा फ़ोल्डर चुनें।
SelectDirectoryLabel=कृपया बताएँ कि अगली डिस्क कहाँ है।

; *** Installation phase messages
SetupAborted=सेटअप पूरा नहीं हुआ।%n%nकृपया समस्या ठीक करें और सेटअप फिर से चलाएँ।
AbortRetryIgnoreSelectAction=क्या करना है चुनें
AbortRetryIgnoreRetry=फिर से कोशिश करें(&T)
AbortRetryIgnoreIgnore=त्रुटि को अनदेखा करके जारी रखें(&I)
AbortRetryIgnoreCancel=इंस्टॉलेशन रद्द करें
RetryCancelSelectAction=क्या करना है चुनें
RetryCancelRetry=फिर से कोशिश करें(&T)
RetryCancelCancel=रद्द करें

; *** Installation status messages
StatusClosingApplications=ऐप्लिकेशन बंद किए जा रहे हैं...
StatusCreateDirs=फ़ोल्डर बनाए जा रहे हैं...
StatusExtractFiles=फ़ाइलें निकाली जा रही हैं...
StatusDownloadFiles=फ़ाइलें डाउनलोड हो रही हैं...
StatusCreateIcons=शॉर्टकट बनाए जा रहे हैं...
StatusCreateIniEntries=INI प्रविष्टियाँ बनाई जा रही हैं...
StatusCreateRegistryEntries=रजिस्ट्री प्रविष्टियाँ बनाई जा रही हैं...
StatusRegisterFiles=फ़ाइलें रजिस्टर की जा रही हैं...
StatusSavingUninstall=अनइंस्टॉल की जानकारी सहेजी जा रही है...
StatusRunProgram=इंस्टॉलेशन पूरा किया जा रहा है...
StatusRestartingApplications=ऐप्लिकेशन फिर से शुरू किए जा रहे हैं...
StatusRollback=बदलाव वापस लिए जा रहे हैं...

; *** Misc. errors
ErrorInternal2=आंतरिक त्रुटि: %1
ErrorFunctionFailedNoCode=%1 विफल रहा
ErrorFunctionFailed=%1 विफल रहा; कोड %2
ErrorFunctionFailedWithMessage=%1 विफल रहा; कोड %2.%n%3
ErrorExecutingProgram=फ़ाइल नहीं चल सकी:%n%1

; *** Registry errors
ErrorRegOpenKey=रजिस्ट्री कुंजी खोलते समय त्रुटि:%n%1\%2
ErrorRegCreateKey=रजिस्ट्री कुंजी बनाते समय त्रुटि:%n%1\%2
ErrorRegWriteKey=रजिस्ट्री कुंजी में लिखते समय त्रुटि:%n%1\%2

; *** INI errors
ErrorIniEntry=फ़ाइल "%1" में INI प्रविष्टि बनाते समय त्रुटि।

; *** File copying errors
FileAbortRetryIgnoreSkipNotRecommended=यह फ़ाइल छोड़ दें (सुझाया नहीं जाता)(&S)
FileAbortRetryIgnoreIgnoreNotRecommended=त्रुटि को अनदेखा करके जारी रखें (सुझाया नहीं जाता)(&I)
SourceIsCorrupted=स्रोत फ़ाइल खराब है
SourceDoesntExist=स्रोत फ़ाइल "%1" मौजूद नहीं है
SourceVerificationFailed=स्रोत फ़ाइल की जाँच विफल रही: %1
VerificationSignatureDoesntExist=सिग्नेचर फ़ाइल "%1" मौजूद नहीं है
VerificationSignatureInvalid=सिग्नेचर फ़ाइल "%1" अमान्य है
VerificationKeyNotFound=सिग्नेचर फ़ाइल "%1" एक अज्ञात कुंजी का उपयोग करती है
VerificationFileNameIncorrect=फ़ाइल का नाम गलत है
VerificationFileTagIncorrect=फ़ाइल का टैग गलत है
VerificationFileSizeIncorrect=फ़ाइल का आकार गलत है
VerificationFileHashIncorrect=फ़ाइल का हैश गलत है
ExistingFileReadOnly2=मौजूदा फ़ाइल को बदला नहीं जा सका क्योंकि वह केवल-पढ़ने (read-only) के रूप में चिह्नित है।
ExistingFileReadOnlyRetry=केवल-पढ़ने की विशेषता हटाकर फिर से कोशिश करें(&R)
ExistingFileReadOnlyKeepExisting=मौजूदा फ़ाइल रखें(&K)
ErrorReadingExistingDest=मौजूदा फ़ाइल पढ़ते समय त्रुटि हुई:
FileExistsSelectAction=क्या करना है चुनें
FileExists2=फ़ाइल पहले से मौजूद है।
FileExistsOverwriteExisting=मौजूदा फ़ाइल को बदलें(&O)
FileExistsKeepExisting=मौजूदा फ़ाइल रखें(&K)
FileExistsOverwriteOrKeepAll=आगे के ऐसे सभी मामलों में यही करें(&D)
ExistingFileNewerSelectAction=क्या करना है चुनें
ExistingFileNewer2=मौजूदा फ़ाइल उस फ़ाइल से नई है जिसे सेटअप इंस्टॉल करना चाहता है।
ExistingFileNewerOverwriteExisting=मौजूदा फ़ाइल को बदलें(&O)
ExistingFileNewerKeepExisting=मौजूदा फ़ाइल रखें (सुझाया गया)(&K)
ExistingFileNewerOverwriteOrKeepAll=आगे के ऐसे सभी मामलों में यही करें(&D)
ErrorChangingAttr=मौजूदा फ़ाइल की विशेषताएँ बदलते समय त्रुटि हुई:
ErrorCreatingTemp=गंतव्य फ़ोल्डर में फ़ाइल बनाते समय त्रुटि हुई:
ErrorReadingSource=स्रोत फ़ाइल पढ़ते समय त्रुटि हुई:
ErrorCopying=फ़ाइल कॉपी करते समय त्रुटि हुई:
ErrorDownloading=फ़ाइल डाउनलोड करते समय त्रुटि हुई:
ErrorExtracting=आर्काइव से फ़ाइलें निकालते समय त्रुटि हुई:
ErrorReplacingExistingFile=मौजूदा फ़ाइल बदलते समय त्रुटि हुई:
ErrorRestartReplace=RestartReplace विफल रहा:
ErrorRenamingTemp=गंतव्य फ़ोल्डर में फ़ाइल का नाम बदलते समय त्रुटि हुई:
ErrorRegisterServer=DLL/OCX रजिस्टर नहीं हो सका: %1
ErrorRegSvr32Failed=RegSvr32 विफल रहा, निकास कोड %1
ErrorRegisterTypeLib=टाइप लाइब्रेरी रजिस्टर नहीं हो सकी: %1

; *** Uninstall display name markings
UninstallDisplayNameMark=%1 (%2)
UninstallDisplayNameMarks=%1 (%2, %3)
UninstallDisplayNameMark32Bit=32-बिट
UninstallDisplayNameMark64Bit=64-बिट
UninstallDisplayNameMarkAllUsers=सभी उपयोगकर्ता
UninstallDisplayNameMarkCurrentUser=मौजूदा उपयोगकर्ता

; *** Post-installation errors
ErrorOpeningReadme=README फ़ाइल खोलते समय त्रुटि हुई।
ErrorRestartingComputer=सेटअप कंप्यूटर रीस्टार्ट नहीं कर सका। कृपया इसे स्वयं रीस्टार्ट करें।

; *** Uninstaller messages
UninstallNotFound=फ़ाइल "%1" मौजूद नहीं है। अनइंस्टॉल नहीं हो सकता।
UninstallOpenError=फ़ाइल "%1" खोली नहीं जा सकी। अनइंस्टॉल नहीं हो सकता
UninstallUnsupportedVer=अनइंस्टॉल लॉग फ़ाइल "%1" का फ़ॉर्मेट अनइंस्टॉलर का यह संस्करण नहीं पहचानता। अनइंस्टॉल नहीं हो सकता
UninstallUnknownEntry=अनइंस्टॉल लॉग में एक अज्ञात प्रविष्टि (%1) मिली
ConfirmUninstall=क्या आप सच में %1 और उसके सभी कॉम्पोनेंट पूरी तरह हटाना चाहते हैं?
UninstallOnlyOnWin64=यह इंस्टॉलेशन केवल 64-बिट Windows पर अनइंस्टॉल हो सकता है।
OnlyAdminCanUninstall=यह इंस्टॉलेशन केवल व्यवस्थापक अधिकार वाला उपयोगकर्ता अनइंस्टॉल कर सकता है।
UninstallStatusLabel=कृपया प्रतीक्षा करें, %1 आपके कंप्यूटर से हटाया जा रहा है।
UninstalledAll=%1 आपके कंप्यूटर से सफलतापूर्वक हटा दिया गया।
UninstalledMost=%1 का अनइंस्टॉल पूरा हुआ।%n%nकुछ चीज़ें हटाई नहीं जा सकीं। इन्हें आप स्वयं हटा सकते हैं।
UninstalledAndNeedsRestart=%1 का अनइंस्टॉल पूरा करने के लिए आपका कंप्यूटर रीस्टार्ट करना होगा।%n%nक्या आप अभी रीस्टार्ट करना चाहते हैं?
UninstallDataCorrupted=फ़ाइल "%1" खराब है। अनइंस्टॉल नहीं हो सकता

; *** Uninstallation phase messages
ConfirmDeleteSharedFileTitle=साझा फ़ाइल हटाएँ?
ConfirmDeleteSharedFile2=सिस्टम के अनुसार यह साझा फ़ाइल अब किसी प्रोग्राम द्वारा उपयोग नहीं हो रही। क्या अनइंस्टॉल इस साझा फ़ाइल को हटा दे?%n%nअगर कोई प्रोग्राम अब भी इस फ़ाइल का उपयोग कर रहा है और इसे हटा दिया गया, तो वह प्रोग्राम ठीक से काम नहीं कर सकता। अगर आपको पक्का नहीं पता, तो नहीं चुनें। फ़ाइल को सिस्टम पर छोड़ने से कोई नुकसान नहीं होगा।
SharedFileNameLabel=फ़ाइल का नाम:
SharedFileLocationLabel=स्थान:
WizardUninstalling=अनइंस्टॉल की स्थिति
StatusUninstalling=%1 अनइंस्टॉल हो रहा है...

; *** Shutdown block reasons
ShutdownBlockReasonInstallingApp=%1 इंस्टॉल हो रहा है।
ShutdownBlockReasonUninstallingApp=%1 अनइंस्टॉल हो रहा है।

[CustomMessages]

NameAndVersion=%1 संस्करण %2
AdditionalIcons=अतिरिक्त शॉर्टकट:
CreateDesktopIcon=डेस्कटॉप पर शॉर्टकट बनाएँ(&D)
CreateQuickLaunchIcon=क्विक लॉन्च शॉर्टकट बनाएँ(&Q)
ProgramOnTheWeb=वेब पर %1
UninstallProgram=%1 अनइंस्टॉल करें
LaunchProgram=%1 शुरू करें
AssocFileExtension=%2 फ़ाइल एक्सटेंशन को %1 से जोड़ें(&A)
AssocingFileExtension=%2 फ़ाइल एक्सटेंशन को %1 से जोड़ा जा रहा है...
AutoStartProgramGroupDescription=स्टार्टअप:
AutoStartProgram=%1 अपने-आप शुरू करें
AddonHostProgramNotFound=आपके चुने गए फ़ोल्डर में %1 नहीं मिला।%n%nक्या आप फिर भी जारी रखना चाहते हैं?
