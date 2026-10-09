/* Account controls, readable documents and explicit invitation registration. */
function legalLink(key,text){const link=document.createElement('a');link.textContent=text;link.dataset.legal=key;link.href='/legal/'+key+'?lang='+uiLanguage();return link;}
function legalLinks(host){for(const [key,text] of [['privacy','Конфиденциальность'],['terms','Условия использования'],['cookies','Хранение в браузере'],['about','О сервисе'],['licenses','Лицензии']])host.append(legalLink(key,text));}
function updateLegalLinks(){document.querySelectorAll('[data-legal]').forEach(link=>link.href='/legal/'+link.dataset.legal+'?lang='+uiLanguage());}
function documentsPage(host){
 host.append(node('h1',null,'Документы и соглашения'),node('p','documents-intro','Midiary — личный независимый проект. Он не представляет МГУ, факультеты или руководство университета.'));
 const grid=node('div','documents-grid');
 for(const [key,title,description] of [
  ['privacy','Политика конфиденциальности','Какие данные хранятся, зачем и как их удалить.'],
  ['terms','Условия использования','Правила аккаунта, общих материалов и отзывов.'],
  ['cookies','Хранение в браузере','Сессия входа и настройки языка и оформления.'],
  ['consent','Согласие на обработку данных','Отдельное согласие при регистрации.'],
  ['guardian','Согласие представителя','Порядок регистрации участников младше 18 лет.'],
  ['copyright','Права на материалы','Правила загрузки и обращения правообладателей.'],
  ['about','О проекте','Владелец, контакты и независимый статус Midiary.'],
  ['licenses','Лицензии','Источники и лицензии используемых компонентов.']
 ]){const link=legalLink(key,'');link.className='document-link';link.append(node('strong',null,title),node('span',null,description));grid.append(link);}
 host.append(grid,button('Вернуться в профиль',()=>go('profile')));
}
async function registrationFields(form,submit){
 const age=document.createElement('select');age.className='fd-input';age.required=true;age.name='age_group';
 for(const [value,text] of [['','Выберите возрастную категорию'],['adult','Мне 18 лет или больше'],['minor','Мне меньше 18 лет']]){const o=new Option(text,value);age.add(o);}
 const label=node('label','privacy-age','Возрастная категория');label.append(age);form.insertBefore(label,submit);
 const hint=node('p','muted','Для участника младше 18 лет администратор выдаёт специальный код после получения отдельного согласия представителя и проверки его полномочий.');hint.append(' ',legalLink('guardian','Согласие представителя'));form.insertBefore(hint,submit);
 const terms=node('input');terms.type='checkbox';terms.required=true;terms.name='terms_accepted';
 const termsLabel=node('label','privacy-check');termsLabel.append(terms,node('span',null,'Принимаю условия использования'),legalLink('terms','Прочитать условия'));form.insertBefore(termsLabel,submit);
 const privacy=node('input');privacy.type='checkbox';privacy.required=true;privacy.name='privacy_accepted';
 const privacyLabel=node('label','privacy-check'),privacyText=node('span',null,'Отдельно согласен на обработку моих данных'),consentLink=legalLink('consent','Прочитать согласие');privacyLabel.append(privacy,privacyText,consentLink);form.insertBefore(privacyLabel,submit);
 age.onchange=()=>{privacy.checked=false;privacyText.textContent=age.value==='minor'?'Ознакомился с порядком обработки данных. Для регистрации нужно отдельное согласие представителя.':'Отдельно согласен на обработку моих данных';consentLink.dataset.legal=age.value==='minor'?'guardian':'consent';updateLegalLinks();};
 const status=node('p','muted');status.setAttribute('role','status');form.insertBefore(status,submit);submit.disabled=true;
 try{const info=await api('legal');form.dataset.legalVersion=info.version;form.dataset.legalReady=info.ready?'1':'';submit.disabled=!info.ready;if(!info.ready)status.textContent='Администратор ещё не заполнил сведения о владельце сервиса. Регистрация временно недоступна.';}
 catch(error){status.textContent=error.message;}
}
function registrationPayload(form){return {age_group:form.elements.age_group.value,terms_accepted:form.elements.terms_accepted.checked,privacy_accepted:form.elements.privacy_accepted.checked,legal_version:form.dataset.legalVersion};}
async function firstVisitConsent(){
 const info=await api('legal/consent');if(!info.required)return false;
 document.getElementById('nav').hidden=true;root.dataset.page='consent';page='consent';screen.replaceChildren();const host=node('section','fd-detail-page first-visit-consent');screen.append(host);
 host.append(node('h1',null,'Перед первым входом'),node('p',null,'Прочитайте документы и подтвердите согласие. Чекбоксы не отмечены заранее. Подтверждение сохранится для вашего аккаунта в Telegram, MAX и на сайте.'),languagePicker());
 const form=node('form'),save=node('button','fd-primary','Согласен, открыть дневник');save.type='submit';form.append(save);host.append(form);await registrationFields(form,save);
 const guardian=inputField(form,'Код после подтверждения представителя','password');guardian.closest('label').hidden=true;host.append(button('Выйти из аккаунта',logout));
 const age=form.elements.age_group,previous=age.onchange;age.onchange=()=>{previous();guardian.closest('label').hidden=age.value!=='minor'||info.guardian_confirmed;guardian.required=age.value==='minor'&&!info.guardian_confirmed;};
 form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{await post('legal/consent',{...registrationPayload(form),guardian_code:guardian.value});await enterBrowser({csrf});}catch(error){fail(error);}finally{save.disabled=!form.dataset.legalReady;}};
 save.disabled=!info.ready||!form.dataset.legalReady;return true;
}
function privacyDialog(kind){
 const dialog=node('dialog','privacy-dialog');const title=node('h2',null,kind==='account'?'Удалить аккаунт?':'Удалить личные записи?');title.id='privacy-delete-title';dialog.setAttribute('aria-labelledby',title.id);
 const text=kind==='account'?'Аккаунт, личные записи, закладки, отзывы и файлы с подтверждённым авторством будут удалены. Вы выйдете из аккаунта. Общие записи группы сохранятся без вашего имени. Восстановление аккаунта этой кнопкой невозможно.':'Личные записи, закладки, дополнительные пары и настройки уведомлений будут удалены. Аккаунт, отзывы и общие материалы сохранятся.';
 const check=node('input');check.type='checkbox';const row=node('label','privacy-check');row.append(check,node('span',null,'Понимаю последствия и подтверждаю удаление'));const status=node('p');status.setAttribute('role','status');
 const confirm=button('Подтвердить удаление',async()=>{confirm.disabled=true;try{const result=await post('account/delete',{kind,confirm:true});dialog.close();if(kind==='account'){releaseBrowserPush();rememberLogout(true);loginGeneration++;me=undefined;csrf='';contents=[];personal=[];days=[];scheduleEvents=[];topics=[];history=[];selectedLesson=undefined;selectedTeacher='';lastLoadAt=0;updateBack();await browserLogin(false);fail(Error(result.pending?'Удаление выполняется. Вход в этот аккаунт уже отключён.':'Аккаунт удалён.'));}else{releaseBrowserPush();await load(true);await go('profile',false);fail(Error(result.pending?'Удаление выполняется.':'Личные записи удалены.'));}}catch(error){status.textContent=error.message;confirm.disabled=!check.checked;}});confirm.disabled=true;check.onchange=()=>confirm.disabled=!check.checked;
 dialog.append(title,node('p',null,text),row,button('Отмена',()=>dialog.close()),confirm,status);root.append(dialog);dialog.addEventListener('close',()=>dialog.remove(),{once:true});dialog.showModal();
}
function dataDownload(value){const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='midiary-my-data.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);}
async function privacyPanel(host){
 const section=node('section','privacy-panel');section.append(node('h2',null,'Мои данные'),button('Документы и соглашения',()=>go('documents'),'fd-secondary profile-documents'));
 section.append(button('Выгрузить мои данные',async()=>dataDownload(await api('account/export'))),button('Удалить личные записи',()=>privacyDialog('personal')));if(!me.admin)section.append(button('Удалить аккаунт',()=>privacyDialog('account')));
 section.append(node('p','muted','Для удаления старого файла с неустановленным авторством обратитесь к владельцу сервиса. Контакт указан в политике конфиденциальности.'));host.append(section);
 const row=node('label','privacy-check'),enabled=node('input');enabled.type='checkbox';enabled.disabled=true;row.append(enabled,node('span',null,'Получать общие объявления в Telegram и MAX'));const status=node('p','muted');status.setAttribute('role','status');section.append(row,node('p','muted','Отключение общих объявлений не отключает напоминания о парах и дедлайнах.'),status);
 try{const prefs=await api('account/announcements');if(!section.isConnected)return;enabled.checked=prefs.enabled;enabled.disabled=false;enabled.onchange=async()=>{enabled.disabled=true;try{await post('account/announcements',{enabled:enabled.checked});status.textContent='Настройки сохранены.';}catch(error){enabled.checked=!enabled.checked;status.textContent=error.message;}finally{enabled.disabled=false;}};}catch(error){status.textContent=error.message;}
 if(me.admin)operatorPanel(section);
}
function operatorPanel(host){
 const details=node('details','fd-hw-editor');details.append(node('summary',null,'Сведения о владельце сервиса'));const panel=node('div');details.append(panel);host.append(details);
 details.ontoggle=async()=>{if(!details.open||panel.childNodes.length)return;try{const info=await api('admin/legal'),form=node('form');form.append(node('p','muted','Укажите реальные сведения. Они появятся в публичных документах. Без обязательных сведений новая регистрация закрыта.'));const fields={};
 for(const [key,text] of [['operator','ФИО владельца или название организации'],['contact','Контакт: email или Telegram'],['address','Адрес для обращений (необязательно)'],['hosting_country','Страна размещения VPS'],['hosting_provider','Хостинг-провайдер (необязательно)']]){fields[key]=inputField(form,text);fields[key].maxLength=300;fields[key].value=info.operator[key];fields[key].required=['operator','contact','hosting_country'].includes(key);}
 const status=node('p','muted');status.setAttribute('role','status');const save=node('button','fd-primary','Сохранить сведения');save.type='submit';form.append(save,status);form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{await post('admin/legal',Object.fromEntries(Object.entries(fields).map(([key,field])=>[key,field.value])));status.textContent='Сведения сохранены. Проверьте публичные документы.';}catch(error){status.textContent=error.message;}finally{save.disabled=false;}};panel.append(form);}catch(error){panel.append(node('p',null,error.message));}};
}
document.addEventListener('DOMContentLoaded',()=>{
 const footer=document.getElementById('legal-footer');legalLinks(footer);
 new MutationObserver(updateLegalLinks).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
 let seen=false;try{seen=localStorage.getItem('midiary-storage-notice')==='2026-10-04';}catch{}
 if(!seen){const panel=node('aside','storage-notice');panel.setAttribute('aria-label','Хранение в браузере');panel.append(node('p',null,'Midiary сохраняет сессию входа, язык и настройки в браузере. Аналитика и рекламные трекеры не используются.'),legalLink('cookies','Подробнее о хранении'),button('Понятно',()=>{try{localStorage.setItem('midiary-storage-notice','2026-10-04');}catch{}panel.remove();}));footer.before(panel);}
});
