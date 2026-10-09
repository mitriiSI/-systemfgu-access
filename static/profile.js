/* A compact profile and one stable place for identity and account settings. */
function updateHeaderIdentity(){
 const bar=document.querySelector('.header-identity'),profile=document.getElementById('header-profile'),group=document.getElementById('header-group'),help=document.getElementById('header-help');
 bar.hidden=help.hidden=!me;
 if(!me){profile.replaceChildren();group.replaceChildren();return;}
 const avatar=node('span','identity-avatar',me.name.split(/\s+/).slice(0,2).map(part=>part[0]).join(''));avatar.dataset.personName='';
 const copy=node('span','identity-copy'),name=node('strong',null,me.name);name.dataset.personName='';copy.append(name,node('span',null,'Профиль'));
 profile.replaceChildren(avatar,copy);profile.setAttribute('aria-label','Открыть профиль: '+me.name);
 group.textContent=(facultyInfo[me.faculty]?.short||'Учёба')+' · '+(me.group||'Выбрать группу');
 group.setAttribute('aria-label','Факультет и группа: '+group.textContent);
 profile.onclick=()=>go('profile');group.onclick=()=>go('study-group');help.onclick=()=>startDiaryTour();
}
function profilePanel(host,title,cls){
 const section=node('section','profile-panel '+cls);section.append(node('h2',null,title));host.append(section);return section;
}
function renderProfile(host){
 host.classList.add('profile-page');host.append(node('h1',null,'Профиль'));
 const study=profilePanel(host,'Моя учёба','profile-study'),row=node('div','profile-study-row');
 row.append(node('p',null,(facultyInfo[me.faculty]?.short||'Учёба')+' · '+me.group),button('Факультет и группа',()=>go('study-group'),'fd-secondary profile-study-change'));study.append(row);
 subgroupSettings(study).catch(fail);importChoicesHint(study);
 if(me.group_comparison){const comparison=profilePanel(host,'Дополнительное расписание','profile-comparison');comparison.append(button('Подпись и уведомления'+(me.group_comparison_admin?' · сообщения':''),()=>go('comparison-settings'),'fd-secondary comparison-profile-entry'));}
 const notifications=profilePanel(host,'Уведомления','profile-notifications');
 notificationChannelSettings(notifications);reminderSettings(notifications);homeworkReminderSettings(notifications);webPushSettings(notifications);
 const accounts=profilePanel(host,'Подключённые аккаунты','profile-accounts');
 accountAccess(accounts);telegramAccountSection(accounts);maxAccountSection(accounts);
 const support=node('a','fd-secondary support-bot-link','Поддержка · @midiarybot');support.href='https://t.me/midiarybot';support.target='_blank';support.rel='noopener noreferrer';accounts.append(support);
 const preferences=profilePanel(host,'Личные настройки','profile-preferences'),display=node('p',null,me.name);display.dataset.personName='';preferences.append(display);
 profileNameEditor(preferences,display);preferences.append(languagePicker());lessonHistoryPanel(preferences);subscriptionPanel(preferences).catch(fail);
 const data=node('div','profile-data');host.append(data);privacyPanel(data).catch(fail);
 if(me.admin){const admin=profilePanel(host,'Управление сервисом','profile-administration');admin.append(button('Пользователи и уведомления',()=>go('admin-users'),'fd-secondary admin-users-entry'),button('Обновления и каналы',()=>go('admin-channels'),'fd-secondary'));privacyInvitations(admin);admin.append(node('p','muted','Команды управления участниками и подтверждения изменений доступны в боте: /help'));}
}
async function telegramAccountSection(host){
 const section=node('section','telegram-account account-connection'),status=node('p','muted');status.setAttribute('role','status');section.append(node('h3',null,'Telegram'),status);host.append(section);
 try{const [prefs,bots]=await Promise.all([api('notification-channels'),api('bots/info')]);if(!section.isConnected)return;
  status.textContent=prefs.connected.telegram?'Telegram подключён.':'Для подключения откройте бота и отправьте /link с вашим кодом доступа.';
  const link=node('a','fd-secondary','Открыть бота Telegram');link.href=bots.telegram;link.target='_blank';link.rel='noopener noreferrer';section.append(link);
 }catch(error){status.textContent=error.message;}
}

Object.assign(midiaryTranslations,{
 'Подключённые аккаунты':['Connected accounts','已关联的账号'],
 'Моя учёба':['My studies','我的学习'],
 'Личные настройки':['Personal settings','个人设置'],
 'Управление сервисом':['Diary administration','日记管理'],
 'Уведомления':['Notifications','通知'],
 'Открыть бота Telegram':['Open Telegram bot','打开Telegram机器人'],
 'Telegram подключён.':['Telegram is connected.','Telegram已关联。'],
 'Для подключения откройте бота и отправьте /link с вашим кодом доступа.':['To connect, open the bot and send /link with your access code.','要关联账号，请打开机器人并发送/link和你的访问码。'],
 'Сначала добавьте удобное время. Можно сохранить до 4 напоминаний в день.':['Add your preferred times. You can save up to 4 reminders a day.','添加你喜欢的时间。每天最多可以保存4个提醒。'],
 'Выбранные времена (МСК)':['Selected times (Moscow)','已选择的时间（莫斯科）'],
 'Добавить время напоминания (МСК)':['Add a reminder time (Moscow)','添加提醒时间（莫斯科）'],
 'Пока время не выбрано.':['No times selected yet.','尚未选择时间。'],
 'Это время уже добавлено.':['This time is already added.','此时间已添加。'],
 'Часть расписания не удалось обновить. Сохранённые занятия доступны.':['Some timetable updates failed. Saved classes remain available.','部分课表未能更新。已保存的课程仍可使用。'],
 'Проверяем обновления расписания…':['Checking timetable updates…','正在检查课表更新…']
});

const diaryHeader=document.querySelector('.fd-telegram');
new ResizeObserver(()=>{
 const height=Math.ceil(diaryHeader.querySelector('.brand-capsule,.brand-anchor')?.getBoundingClientRect().height||40);
 document.getElementById('fgu-diary-design').style.setProperty('--diary-header-height',height+'px');
 document.documentElement.style.setProperty('--diary-scroll-offset',(height+28)+'px');
}).observe(diaryHeader);
