/* A first-visit walkthrough of real controls; no schedule changes are made. */
const diaryTourCopy={
 ru:{replay:'Знакомство с расписанием',label:'Знакомство с Midiary',skip:'Позже',close:'Закрыть знакомство',back:'Назад',next:'Дальше',start:'Начать знакомство',done:'Открыть расписание',step:'Шаг',of:'из',
  welcome:['Добро пожаловать в Midiary','Ваше расписание, задания и материалы — в одном месте. За минуту покажем, где что находится.'],
  dates:['Выберите свой день','Нажмите на дату, чтобы посмотреть пары. Стрелки переключают недели, а значок календаря открывает весь месяц. На телефоне можно листать свайпом.'],
  subject:['Всё по предмету','Нажмите на название предмета: внутри можно записать или изменить ДЗ, добавить конспекты и файлы. Имя преподавателя рядом с типом занятия открывает его страницу. Загруженные файлы показаны под предметом отдельными ссылками.'],
  settings:['Действия под шестерёнкой','Здесь можно добавить файл, записать или изменить ДЗ и убрать пару из своего расписания на эту дату. Список преподавателей редактируется внутри предмета.'],
  custom:['Добавьте своё занятие','Откройте этот блок, чтобы добавить пару или событие. Выберите «Только я» для личной записи и включите повторение, если оно нужно каждую неделю.'],
  navigation:['Главные разделы — внизу','Нажмите Midiary сверху, чтобы вернуться к сегодняшнему расписанию. Внизу — личные баллы по истории, преподаватели с отзывами, учебные материалы и дедлайны.'],
  profile:['Профиль открывается по имени','Здесь можно написать своё имя, настроить уведомления и вернуть свою удалённую пару в «Истории моих пар». Для ФИЯР и ФГП выберите факультет и группу самостоятельно и загрузите расписание.'],
  finish:['Всё готово для учёбы','Осваивайтесь в своём темпе. Это знакомство всегда можно открыть снова из профиля.']},
 en:{replay:'Meet your diary',label:'Welcome to Midiary',skip:'Later',close:'Close walkthrough',back:'Back',next:'Next',start:'Show me around',done:'Open diary',step:'Step',of:'of',
  welcome:['Welcome to Midiary','Your timetable, assignments and materials in one place. A quick tour will show you where everything lives.'],
  dates:['Choose your day','Tap a date to see your classes. Arrows change weeks; the calendar opens the whole month. On a phone, you can swipe too.'],
  subject:['Everything for a subject','Tap the subject name to add or edit homework and attach notes or files. The teacher’s name next to the class type opens their page. Uploaded files appear below the subject as separate links.'],
  settings:['Actions behind the gear','Add a file, add or edit homework, or hide a class for this date in your own timetable. Edit the teacher list inside the subject.'],
  custom:['Add your own class','Open this section to add a class or event. Choose “Only me” for a personal entry, and repeat it weekly if needed.'],
  navigation:['Your main sections','Tap Midiary at the top to return to today’s schedule. The bottom tabs contain personal history points, teachers and reviews, study materials, and deadlines.'],
  profile:['Tap your name for your profile','Edit your name, set up notifications, or restore your deleted class in “My class history”. For Foreign Languages and Global Studies, choose your study group and upload your timetable.'],
  finish:['Ready for your studies','Explore at your own pace. You can always restart this walkthrough from your profile.']},
 zh:{replay:'认识学习日记',label:'认识 Midiary',skip:'稍后',close:'关闭介绍',back:'上一步',next:'下一步',start:'开始介绍',done:'打开日记',step:'第',of:'／',
  welcome:['欢迎来到 Midiary','课表、作业和资料集中在一个地方。用一分钟了解各项功能。'],
  dates:['选择日期','点击日期查看课程。箭头切换星期，日历图标打开整月。在手机上也可以滑动切换。'],
  subject:['科目相关内容','点击科目名称即可添加或修改作业、笔记和文件。点击课程类型旁的教师姓名打开教师页面。上传的文件在科目下方分别显示为链接。'],
  settings:['齿轮里的操作','可以添加文件、添加或修改作业，或在自己的课表中隐藏当天的课程。教师名单在科目页面内编辑。'],
  custom:['添加自己的课程','打开此栏添加课程或活动。选择“仅我”创建个人记录，需要时可设置每周重复。'],
  navigation:['主要功能在底部','点击顶部的 Midiary 返回今天的课表。底部有历史课程个人积分、教师及评价、学习资料和截止日期。'],
  profile:['点击姓名打开个人资料','修改姓名、设置通知，或在“我的课程历史”中恢复删除的个人课程。班级由管理员指定。'],
  finish:['准备好开始学习','按自己的节奏探索。随时可以从个人资料中再次打开本介绍。']}
};
Object.assign(diaryTourCopy.ru,{
 welcome:['Освоим весь дневник','Знакомство открывает настоящие разделы и показывает нужные кнопки. Можно идти по шагам или сразу выбрать раздел. Ваши записи и настройки сохраняются.'],
 calendar:['Календарь целиком','Здесь можно открыть любую дату. Выделенный день — выбранный вами. Кнопка возврата пар восстанавливает занятия, которые вы скрыли из своего расписания.'],
 homework:['Запишите задание внутри предмета','Откройте «Записать или изменить ДЗ», введите задание и сохраните. Оно будет видно вашей учебной группе. На главной странице строка ДЗ появляется, когда задание записано.'],
 lessonFiles:['Файлы к конкретной паре','В этом блоке прикрепляют конспекты и выполненные задания. Нажмите на файл, чтобы сохранить или отправить его через системное меню. Название поможет другим быстро найти нужный материал.'],
 lessonDeadline:['Назначьте срок сдачи','Выберите дату и время по Москве. Срок будет общим для группы, а напоминания каждый включает для себя. Он появится и в разделе «Дедлайны».'],
 teachers:['Найдите преподавателя','Поиск помогает найти преподавателя по имени. Нажмите на карточку, чтобы посмотреть оценки и отзывы. Если у предмета несколько преподавателей, в расписании они перечислены в столбик.'],
 teacherNotes:['Ваши записи о преподавателе','Эта характеристика видна только вам. Ниже находится общая характеристика: её видит группа, а право редактирования задаёт администратор.'],
 reviews:['Оценки и отзывы','Здесь можно оценить понятность объяснений, знания и общение, написать комментарий и выбрать, показывать ли имя. Отзывы отражают опыт участников.'],
 materials:['Все материалы в одном разделе','Переключайте «Все файлы», «Конспекты», «Литература» и «Личные записи». Файлы собраны по предметам. Книгу или документ можно открыть, скачать и продолжить читать позже.'],
 collections:['Подборки по предмету','Откройте этот блок, выберите конспекты, ДЗ, презентации или проекты. Создайте подборку с названием предмета, затем загрузите в неё файлы. Они появятся в общем списке материалов.'],
 literature:['Литература и книги','Выберите тему в списке. Здесь находятся книги этой темы и форма добавления файла. Администратор может создавать новые темы. Загруженные книги доступны в разделе «Литература».'],
 notes:['Личные заметки','Нажмите «Новая заметка», задайте название и текст, затем сохраните. Эти записи видны только вам. Переключение на другие материалы не превращает заметки в общие файлы.'],
 deadlines:['Все сроки сдачи','Задания распределены по близким, далёким и прошедшим срокам. Откройте «Напоминания» у нужного задания и выберите один или несколько интервалов. Новый срок добавляется внутри предмета.'],
 profile:['Ваш профиль','Своё имя и фамилию можно написать здесь. Для ФИЯР и ФГП выберите факультет и группу и загрузите расписание. Группу ФГУ назначает администратор. Знакомство можно снова открыть этой кнопкой.'],
 subgroups:['Выберите свою подгруппу','Если расписание предмета разделено, выберите своего преподавателя или подгруппу и сохраните. Например, по информатике это могут быть разные преподаватели. Общие лекции останутся, а напоминания учтут выбор.'],
 history:['Верните свою удалённую пару','В истории видны изменения созданных вами пар: добавление, редактирование, удаление и восстановление. Нажмите «Восстановить пару» или «Вернуть эту версию» у нужной записи.'],
 channels:['Выберите, куда писать','Telegram, MAX и уведомления сайта можно включать отдельно. Этот выбор действует для пар, дедлайнов и ДЗ на завтра. Для бота сначала свяжите аккаунт командой /link и кодом доступа.'],
 reminders:['Напоминания о начале пар','Выберите удобные интервалы и нажмите «Сохранить». Можно получать несколько напоминаний. Время занятий и уведомлений указывается по Москве.'],
 homeworkReminders:['ДЗ на завтра','Добавьте одно или несколько удобных времён для сводки. Сообщение приходит, когда к вашим завтрашним занятиям записано ДЗ. Выбранные подгруппы и скрытые пары учитываются.'],
 push:['Уведомления на устройстве','В этом блоке включаются уведомления сайта. На iPhone и iPad сначала добавьте дневник на экран «Домой» через Safari. Затем разрешите уведомления и проверьте их кнопкой в этом блоке.'],
 preferences:['Язык и внешний вид','Язык выбирается в профиле. Значок солнца или луны в верхней панели меняет светлую и тёмную тему. Оформление и фон соответствуют вашему факультету.'],
 account:['Ваш код доступа','Ваш код для входа и привязки бота показан в этом разделе. Сохраните его у себя. Код приглашения администратора и ваш личный код доступа выполняют разные задачи.'],
 privacy:['Управление личными данными','Здесь можно выгрузить свои данные, удалить личные записи и открыть документы сервиса. Удаление требует отдельного подтверждения. Настройка общих объявлений не выключает напоминания о занятиях.'],
 documents:['Документы сервиса','Здесь собраны соглашения, правила и сведения о хранении данных. Каждый документ открывается по своей ссылке. Вернуться в дневник можно стрелкой сверху.'],
 subscription:['Доступ для других факультетов','Это подготовка будущей подписки. Администратор сможет назначить индивидуальную цену или бесплатный доступ. Оплата пока не подключена; ФГУ остаётся бесплатным.'],
 admin:['Приглашения и управление','В профиле администратора находятся коды с лимитом регистраций, разрешения по Telegram ID, назначение групп и настройки поддержки. Пользователь пишет своё имя сам, а учебную группу выбираете вы.'],
 finish:['Теперь вы знаете, где что находится','Знакомство можно повторить из профиля или перейти к отдельному разделу через его содержание. Закроем подсказки и вернём вас туда, откуда вы начали.'],
 contents:'Разделы знакомства',retry:'Повторить',dirty:'Сначала сохраните изменения в форме, затем откройте знакомство.',
 chapters:['Начало','Расписание','Предмет','Преподаватели','Материалы','Дедлайны','Профиль','Доступ']
});
Object.assign(diaryTourCopy.en,{
 welcome:['Explore your whole diary','This tour opens the real sections and points out their controls. Follow every step or jump to a section. Your entries and settings are kept.'],
 calendar:['The full calendar','Open any date here. The highlighted date is your selection. The restore button brings back official classes you hid from your own timetable.'],
 homework:['Homework inside a subject','Open “Add or edit homework”, enter the assignment and save. It is shared with your study group. The main timetable shows a homework row only when an assignment exists.'],
 lessonFiles:['Files for this class','Attach notes and completed assignments here. Tap a file to save or share it using your device’s menu. A clear title helps everyone find the right material.'],
 lessonDeadline:['Set a due date','Choose the date and Moscow time. The due date is shared with the group; each person enables their own reminders. It also appears under “Deadlines”.'],
 teachers:['Find a teacher','Search by name, then open a card for ratings and reviews. When a subject has several teachers, their names appear in a vertical list on the timetable.'],
 teacherNotes:['Your notes about a teacher','This description is private. The shared description below is visible to your group; the administrator controls who may edit it.'],
 reviews:['Ratings and reviews','Rate clarity, knowledge and communication, leave a comment, and choose whether to show your name. Reviews describe participants’ own experiences.'],
 materials:['All your study materials','Switch between all files, notes, literature and personal entries. Files are grouped by subject. Preview or download a book or document and return to it later.'],
 collections:['Subject collections','Open this section and choose notes, homework, presentations or projects. Create a named subject collection and upload files into it. They also appear in the materials list.'],
 literature:['Literature and books','Select a topic to see its books and upload a file. Administrators can create new topics. Uploaded books also appear under the Literature filter.'],
 notes:['Private notes','Tap “New note”, add a title and text, then save. Only you can see these entries. Switching materials filters keeps them private.'],
 deadlines:['Every due date','Assignments are grouped into upcoming, later and past deadlines. Open an assignment’s reminders and choose one or several intervals. Add new deadlines inside a subject.'],
 profile:['Your profile','Write your own name here. For Foreign Languages and Global Studies, choose your faculty and group and upload your timetable. An administrator assigns FGU groups. This button lets you replay the tour.'],
 subgroups:['Choose your subgroup','For a split timetable, choose your teacher or subgroup and save. Common lectures remain visible. The timetable and every reminder channel follow your choice.'],
 history:['Restore your own class','The history records creation, edits, removal and restoration of your classes. Use “Restore class” or “Restore this version” on the relevant entry.'],
 channels:['Where to send reminders','Select Telegram, MAX and website notifications separately. This applies to classes, deadlines and tomorrow’s homework. Link a bot with /link and your access code first.'],
 reminders:['Class reminders','Choose your intervals and save. Multiple reminders are supported. Classes and reminders use Moscow time.'],
 homeworkReminders:['Tomorrow’s homework','Add one or several preferred summary times. A message is sent when your classes tomorrow have homework. Subgroup choices and hidden classes are respected.'],
 push:['Device notifications','Enable website notifications here. On iPhone and iPad, first add the diary to your Home Screen in Safari, then allow notifications and use the test button.'],
 preferences:['Language and appearance','Choose a language in your profile. The sun or moon in the top bar changes the theme. The background matches your faculty.'],
 account:['Your access code','Open this section to view your code for login and bot linking. Keep it private. An administrator’s invitation code and your personal access code serve different purposes.'],
 privacy:['Your personal data','Export your data, remove personal entries, and open the service documents here. Deletion requires a separate confirmation. General announcements have their own setting.'],
 documents:['Service documents','Agreements, rules and storage information are collected here. Each document opens from its own link. Use the top back arrow to return.'],
 subscription:['Access for other faculties','This prepares future subscriptions. Administrators can set a personal price or free access. Payments are not connected yet; FGU remains free.'],
 admin:['Invitations and administration','Your profile contains registration limits, Telegram ID permissions, group assignments and support settings. Members write their own names; you assign study groups.'],
 finish:['You know where everything lives','Replay the tour from your profile or jump to a section from its contents. Closing it returns you to where you started.'],
 contents:'Tour sections',retry:'Retry',dirty:'Save your form changes before starting the tour.',
 chapters:['Welcome','Timetable','Subject','Teachers','Materials','Deadlines','Profile','Access']
});
Object.assign(diaryTourCopy.zh,{
 welcome:['了解整个学习日记','介绍会打开实际页面并指出操作位置。可以逐步浏览，也可以直接选择章节。您的记录和设置会保留。'],
 calendar:['完整日历','在这里打开任意日期。高亮日期是您选中的日期。恢复按钮可以找回您隐藏的正式课程。'],
 homework:['在科目中记录作业','打开“记录或修改作业”，输入内容并保存。作业对班级共享。有作业时，首页才显示作业栏。'],
 lessonFiles:['本次课程的文件','在这里添加笔记和完成的作业。点击文件即可通过系统菜单保存或分享。清晰的名称方便查找。'],
 lessonDeadline:['设置截止时间','选择日期和莫斯科时间。截止时间对班级共享，每个人分别设置自己的提醒。'],
 teachers:['查找教师','按姓名搜索，打开教师卡片查看评分和评价。一个科目有多位教师时，姓名在课表中竖排显示。'],
 teacherNotes:['您的教师笔记','此描述仅自己可见。下方的共享描述对班级可见，由管理员决定编辑权限。'],
 reviews:['评分和评价','评价讲解清晰度、知识和交流，填写评论，并选择是否显示姓名。评价体现参与者的个人经验。'],
 materials:['所有学习资料','切换所有文件、笔记、文献和个人记录。文件按科目整理，可以预览或下载书籍与文档。'],
 collections:['科目资料集','打开此栏，选择笔记、作业、演示或项目。创建科目资料集后上传文件，文件也会显示在资料列表中。'],
 literature:['文献和书籍','选择主题查看书籍并上传文件。管理员可以创建主题。书籍也会出现在文献筛选结果中。'],
 notes:['私人笔记','点击“新笔记”，填写标题和正文后保存。仅您能看到这些记录。切换资料筛选不会公开笔记。'],
 deadlines:['所有截止日期','任务按近期、较远和已过期分类。打开任务提醒并选择一个或多个提前时间。新截止日期在科目页面设置。'],
 profile:['您的个人资料','在这里填写自己的姓名。管理员分配院系和班级，ФГУ默认班级为107пб。此按钮可以重新打开介绍。'],
 subgroups:['选择您的分组','课表分组时，选择教师或小组并保存。共同的讲座保留，课表和各渠道提醒都会遵循您的选择。'],
 history:['恢复自己创建的课程','历史记录显示新增、编辑、删除和恢复操作。在相应记录中点击恢复课程或恢复此版本。'],
 channels:['提醒发送到哪里','分别选择Telegram、MAX和网站通知。适用于课程、截止日期和明日作业。先用/link和访问码关联机器人。'],
 reminders:['上课提醒','选择提醒间隔并保存，可以设置多个提醒。课程和提醒均使用莫斯科时间。'],
 homeworkReminders:['明日作业','添加一个或多个你喜欢的汇总时间。明日课程有作业时才发送消息，并考虑分组选择和隐藏的课程。'],
 push:['设备通知','在此启用网站通知。在iPhone和iPad上，先通过Safari添加到主屏幕，再允许通知并使用测试按钮。'],
 preferences:['语言和外观','在个人资料中选择语言。顶部太阳或月亮按钮切换主题。背景对应您的院系。'],
 account:['您的访问码','打开此栏查看登录和关联机器人的访问码，请妥善保存。管理员邀请码与个人访问码用途不同。'],
 privacy:['个人数据管理','导出数据、删除私人记录和查看服务文档。删除需要单独确认。公告开关不会关闭课程提醒。'],
 documents:['服务文档','这里包含协议、规则和数据存储说明。点击对应链接打开文档，使用顶部返回箭头回到日记。'],
 subscription:['其他院系的访问','这是未来订阅的准备功能。管理员可设置个人价格或免费访问。目前尚未接入支付，ФГУ保持免费。'],
 admin:['邀请和管理','管理员资料中包含注册次数限制、Telegram ID许可、班级分配和支持设置。用户填写姓名，您分配班级。'],
 finish:['您已了解各项功能的位置','可从个人资料重新打开介绍，或通过目录选择章节。关闭后会返回开始时的页面。'],
 contents:'介绍章节',retry:'重试',dirty:'请先保存表单修改，再开始介绍。',
 chapters:['开始','课表','科目','教师','资料','截止日期','个人资料','访问']
});
iconPaths.user='<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>';
function diaryTourText(key){return (diaryTourCopy[uiLanguage()]||diaryTourCopy.ru)[key]||diaryTourCopy.ru[key];}
let diaryTour=null,diaryTourTimer=null;
function maybeDiaryTour(){
 clearTimeout(diaryTourTimer);
 if(!me||me.onboarding_seen||me.needs_group||diaryTour||['consent','login','study-group'].includes(root.dataset.page)||document.getElementById('nav').hidden)return;
 diaryTourTimer=setTimeout(()=>{
  if(me&&!me.onboarding_seen&&!diaryTour&&!root.querySelector('dialog[open]')&&!screen.querySelector('form[data-dirty="true"]')&&!document.hidden&&!['consent','login','study-group'].includes(root.dataset.page))startDiaryTour().catch(fail);
 },650);
}
async function startDiaryTour(){
 clearTimeout(diaryTourTimer);
 if(!me||me.needs_group||diaryTour||root.querySelector('dialog[open]')||['consent','login','study-group'].includes(root.dataset.page))return;
 if(screen.querySelector('form[data-dirty="true"]')||activeUploads.size)throw Error(diaryTourText('dirty'));
 closeLessonSettings();
 const origin={page,day:selectedDay,lesson:selectedLesson,teacher:selectedTeacher,scroll:window.scrollY,focus:document.activeElement,
  filter:screen.querySelector('[data-material-filter][aria-pressed=true]')?.dataset.materialFilter};
 const sampleDays=[...days].sort((a,b)=>Math.abs(Date.parse(a.date)-Date.parse(selectedDay))-Math.abs(Date.parse(b.date)-Date.parse(selectedDay)));
 const sample=sampleDays.map(day=>lessons(day.date)[0]).find(Boolean);
 const teacher=sample?.teachers?.[0]||'';
 const selectMaterial=async key=>{const tab=screen.querySelector('[data-material-filter="'+key+'"]');if(tab)await tab.onclick();};
 const openDetails=selector=>{const detail=screen.querySelector(selector);if(detail)detail.open=true;};
 const steps=[
  {key:'welcome',chapter:0,symbol:'sun'},
  {key:'dates',chapter:1,route:'day',target:'.week',symbol:'calendar'},
  {key:'calendar',chapter:1,route:'calendar',target:'.fd-date.today',symbol:'calendar'},
  ...(sample?[
   {key:'subject',chapter:2,route:'day',prepare:()=>{selectedDay=sample.date;},redraw:true,target:'.lesson-card-body',symbol:'folder'},
   {key:'settings',chapter:2,route:'day',target:'.lesson-settings',symbol:'gear',prepareAfter:()=>{const toggle=screen.querySelector('.lesson-settings-toggle');if(toggle?.getAttribute('aria-expanded')==='false')toggle.click();}},
   {key:'homework',chapter:2,route:'lesson',prepare:()=>{selectedLesson=sample;},target:'[data-homework-editor]',symbol:'notes',prepareAfter:()=>openDetails('[data-homework-editor]')},
   {key:'lessonFiles',chapter:2,route:'lesson',target:'.upload-form',symbol:'folder'},
   {key:'lessonDeadline',chapter:2,route:'lesson',target:'.lesson-deadline',symbol:'calendar'}
  ]:[]),
  {key:'custom',chapter:1,route:'day',target:'.event-editor',symbol:'calendar',prepareAfter:()=>openDetails('.event-editor')},
  {key:'teachers',chapter:3,route:'ratings',target:'.rating-list',symbol:'user'},
  ...(teacher?[
   {key:'teacherNotes',chapter:3,route:'teacher',prepare:()=>{selectedTeacher=teacher;},target:'.fd-note-form',symbol:'notes'},
   {key:'reviews',chapter:3,route:'rating',prepare:()=>{selectedTeacher=teacher;},target:'.review-form',symbol:'user'}
  ]:[]),
  {key:'materials',chapter:4,route:'materials',target:'[data-tour=material-filters]',symbol:'folder',prepareAfter:()=>selectMaterial('all')},
  {key:'collections',chapter:4,route:'materials',target:'[data-tour=collections]',symbol:'folder',prepareAfter:()=>openDetails('[data-tour=collections]')},
  {key:'literature',chapter:4,route:'materials',target:'[data-tour=literature]',symbol:'folder',prepareAfter:()=>{openDetails('[data-tour=literature]');return selectMaterial('literature');}},
  {key:'notes',chapter:4,route:'materials',target:'.notes-shell',symbol:'notes',prepareAfter:()=>selectMaterial('personal')},
  {key:'deadlines',chapter:5,route:'deadlines',target:'.deadline-group',symbol:'calendar'},
  {key:'profile',chapter:6,route:'profile',target:me.admin?'.profile-study':'.profile-name-form',symbol:'user'},
  {key:'subgroups',chapter:6,route:'profile',target:'[data-tour=subgroups]',symbol:'user'},
  {key:'history',chapter:6,route:'profile',target:'[data-tour=lesson-history]',symbol:'calendar',prepareAfter:()=>openDetails('[data-tour=lesson-history]')},
  {key:'channels',chapter:6,route:'profile',target:'.notification-channels',symbol:'more'},
  {key:'reminders',chapter:6,route:'profile',target:'.lesson-reminders',symbol:'calendar'},
  {key:'homeworkReminders',chapter:6,route:'profile',target:'.homework-reminders',symbol:'notes'},
  {key:'push',chapter:6,route:'profile',target:'.web-push-settings',symbol:'more'},
  {key:'preferences',chapter:6,route:'profile',target:'.language-picker',symbol:'sun'},
  {key:'account',chapter:7,route:'profile',target:'[data-tour=account-code]',symbol:'user'},
  {key:'privacy',chapter:7,route:'profile',target:'.privacy-panel',symbol:'user'},
  {key:'documents',chapter:7,route:'documents',target:'.documents-grid',symbol:'folder'},
  ...(me.faculty!=='fgu'?[{key:'subscription',chapter:7,route:'profile',target:'.subscription-personal,[data-tour=subscription]',symbol:'user'}]:[]),
  ...(me.admin?[{key:'admin',chapter:7,route:'profile',target:'.admin-panel',symbol:'user'}]:[]),
  {key:'finish',chapter:0,symbol:'sun'}
 ];
 const dialog=node('dialog','diary-tour'),shade=node('div','tour-shade'),spot=node('div','tour-spotlight'),panel=node('section','tour-panel');
 dialog.dataset.noTranslate='';dialog.setAttribute('aria-label',diaryTourText('label'));shade.setAttribute('aria-hidden','true');spot.setAttribute('aria-hidden','true');
 let index=0,busy=false,closing=false,finished=false,markSeen=true,failedIndex=null,frame=0;
 const progress=node('div','tour-progress'),bar=node('span'),header=node('div','tour-heading'),counter=node('p','tour-counter'),close=button('×',()=>finish(),'tour-close');
 close.setAttribute('aria-label',diaryTourText('close'));progress.setAttribute('aria-hidden','true');progress.append(bar);header.append(counter,close);
 const contents=node('details','tour-contents'),summary=node('summary',null,diaryTourText('contents')),chapterList=node('div','tour-chapters');
 contents.append(summary,chapterList);contents.addEventListener('toggle',schedulePosition);
 for(const chapter of [...new Set(steps.map(step=>step.chapter))]){
  const first=steps.findIndex(step=>step.chapter===chapter),jump=button(diaryTourText('chapters')[chapter],async()=>{contents.open=false;await move(first);},'tour-chapter');
  jump.dataset.chapter=String(chapter);chapterList.append(jump);
 }
 const body=node('div','tour-body'),errorLine=node('p','tour-error'),actions=node('div','tour-actions');
 errorLine.setAttribute('role','status');errorLine.hidden=true;
 const skip=button(diaryTourText('skip'),()=>finish(),'tour-skip'),back=button(diaryTourText('back'),()=>move(index-1),'tour-back');
 const next=button('',()=>failedIndex!==null?move(failedIndex):index===steps.length-1?finish():move(index+1),'tour-next');
 actions.append(skip,back,next);panel.append(progress,header,contents,body,errorLine,actions);dialog.append(shade,spot,panel);root.append(dialog);
 diaryTour={dialog,finish};dialog.showModal();
 async function finish(seen=true){
  if(finished||closing)return;
  closing=true;markSeen=seen;
  if(!busy)await completeFinish();
 }
 async function completeFinish(){
  if(finished)return;finished=true;
  cancelAnimationFrame(frame);window.removeEventListener('resize',schedulePosition);window.removeEventListener('scroll',schedulePosition,true);window.visualViewport?.removeEventListener('resize',schedulePosition);
  closeLessonSettings();
  if(me&&markSeen&&!me.onboarding_seen){me.onboarding_seen=true;post('account/onboarding',{}).catch(()=>{});}
  // Keep the modal open until the original page has been restored.
  try{
   if(me){selectedDay=origin.day;selectedLesson=origin.lesson;selectedTeacher=origin.teacher;await go(origin.page,false);
    if(origin.page==='materials'&&origin.filter)await selectMaterial(origin.filter);
    window.scrollTo(0,origin.scroll);
   }
  }finally{
   diaryTour=null;dialog.close();dialog.remove();
   const focus=origin.focus?.isConnected?origin.focus:screen.querySelector('.profile-tour,.identity-button');focus?.focus({preventScroll:true});
  }
 }
 function schedulePosition(){cancelAnimationFrame(frame);frame=requestAnimationFrame(position);}
 function stepTarget(){
  const step=steps[index],target=step.target?document.querySelector(step.target):null;
  if(!target)return null;
  // Point to a useful control within a large form, leaving it visible beside the panel.
  const focus={lessonFiles:'input[type=file]',lessonDeadline:'input[type=datetime-local]',teacherNotes:'textarea',reviews:'textarea',literature:'select',notes:'.notes-list button',subgroups:'select',documents:'.document-link'}[step.key];
  if(focus&&target.querySelector(focus))return target.querySelector(focus);
  if(target.getBoundingClientRect().height>160){
   for(const selector of ['summary','h2','h1','button','.fd-label','textarea','input','a']){const control=target.querySelector(selector);if(control)return control;}
  }
  return target;
 }
 function position(){
  if(!dialog.isConnected||finished)return;
  const view=window.visualViewport,w=view?.width||innerWidth,h=view?.height||innerHeight,offset=view?.offsetTop||0,margin=16;
  panel.style.width=Math.min(410,w-margin*2)+'px';panel.style.maxHeight=Math.max(120,h-margin*2)+'px';
  const width=panel.offsetWidth,height=panel.offsetHeight,target=stepTarget(),box=target?.getBoundingClientRect();
  const centered=failedIndex!==null||!box||!box.width||!box.height;dialog.classList.toggle('tour-centered',centered);spot.hidden=centered;shade.hidden=!centered;
  let left=(w-width)/2,top=offset+Math.max(margin,(h-height)/2);
  if(!centered){
   const x=Math.max(8,box.left-6),y=Math.max(offset+8,box.top-6),right=Math.min(w-8,box.right+6),bottom=Math.min(offset+h-8,box.bottom+6);
   spot.style.left=x+'px';spot.style.top=y+'px';spot.style.width=Math.max(0,right-x)+'px';spot.style.height=Math.max(0,bottom-y)+'px';spot.style.borderRadius='22px';
   left=Math.min(w-width-margin,Math.max(margin,box.left+(box.width-width)/2));
   top=box.bottom+18;if(top+height>offset+h-margin&&box.top-height-18>=offset+margin)top=box.top-height-18;
   top=Math.max(offset+margin,Math.min(offset+h-height-margin,top));
  }
  panel.style.left=left+'px';panel.style.top=top+'px';
 }
 async function move(value){
  if(busy||closing||value<0||value>=steps.length)return;
  busy=true;next.disabled=back.disabled=true;chapterList.querySelectorAll('button').forEach(button=>button.disabled=true);errorLine.hidden=true;
  try{
   const step=steps[value];closeLessonSettings();
   if(step.prepare)await step.prepare();
   if(step.route&&(page!==step.route||step.redraw))await go(step.route,false);
   if(closing)return;
   if(step.prepareAfter)await step.prepareAfter();
   if(closing)return;
   index=value;failedIndex=null;const copy=diaryTourText(step.key);body.replaceChildren();
   if(step.key==='welcome'||step.key==='finish'){
    const scene=node('div','tour-scene');scene.setAttribute('aria-hidden','true');
    for(let i=0;i<3;i++){const card=node('div','tour-scene-card');card.append(node('span',null,String(new Date().getDate()+i)),node('i'),node('i'));scene.append(card);}
    scene.append(node('div','tour-scene-mark','M'));body.append(scene);
   }else{const symbol=node('div','tour-symbol');symbol.setAttribute('aria-hidden','true');symbol.append(icon(step.symbol));body.append(symbol);}
   body.append(node('p','tour-section',diaryTourText('chapters')[step.chapter]));
   const title=node('h2','tour-title',copy[0]),description=node('p','tour-description',copy[1]);title.id='diary-tour-title';description.id='diary-tour-description';title.tabIndex=-1;
   dialog.setAttribute('aria-labelledby',title.id);dialog.setAttribute('aria-describedby',description.id);body.append(title,description);
   counter.textContent=diaryTourText('step')+' '+(index+1)+' '+diaryTourText('of')+' '+steps.length;counter.setAttribute('aria-live','polite');bar.style.width=((index+1)/steps.length*100)+'%';
   chapterList.querySelectorAll('button').forEach(button=>{const selected=Number(button.dataset.chapter)===step.chapter;button.setAttribute('aria-current',selected?'step':'false');button.setAttribute('aria-pressed',String(selected));});
   back.hidden=index===0;skip.hidden=index===steps.length-1;next.textContent=diaryTourText(index===0?'start':index===steps.length-1?'done':'next')+(index===steps.length-1?'':' →');
   panel.scrollTop=0;let target=stepTarget();
   if(target){target.scrollIntoView({block:'start',behavior:'instant'});window.scrollBy({top:-100,behavior:'instant'});}
   await new Promise(resolve=>requestAnimationFrame(resolve));if(closing)return;
   target=stepTarget();position();
   if(target){const box=target.getBoundingClientRect(),height=window.visualViewport?.height||innerHeight;
    if(box.height<height-panel.offsetHeight-130&&box.bottom+panel.offsetHeight+34>height){window.scrollBy({top:Math.ceil(box.bottom+panel.offsetHeight+34-height),behavior:'instant'});position();}
   }
   title.focus({preventScroll:true});
   if(!matchMedia('(prefers-reduced-motion: reduce)').matches)body.animate([{opacity:0,transform:'translateY(10px)'},{opacity:1,transform:'translateY(0)'}],{duration:260,easing:'cubic-bezier(.2,.7,.2,1)'});
  }catch(error){failedIndex=value;errorLine.textContent=error.message;errorLine.hidden=false;next.textContent=diaryTourText('retry');position();}
  finally{
   busy=false;next.disabled=back.disabled=false;chapterList.querySelectorAll('button').forEach(button=>button.disabled=false);
   if(closing)await completeFinish();
  }
 }
 dialog.addEventListener('cancel',event=>{event.preventDefault();finish();});
 dialog.addEventListener('keydown',event=>{if(event.target.closest('summary,.tour-chapter'))return;if(event.key==='ArrowRight'){event.preventDefault();next.click();}if(event.key==='ArrowLeft'){event.preventDefault();back.click();}});
 window.addEventListener('resize',schedulePosition);window.addEventListener('scroll',schedulePosition,true);window.visualViewport?.addEventListener('resize',schedulePosition);
 await move(0);
}
