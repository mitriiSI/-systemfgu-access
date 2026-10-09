function lessonHistoryPanel(host){
 const details=adminDetails(host,'История моих пар',async panel=>{
  panel.append(node('p','muted','История созданных вами занятий в текущей учебной группе. Можно вернуть удалённую пару или прежнюю версию. Восстановление общих записей сохраняет правила подтверждения администратором.'));
  const status=node('p','muted'),list=node('div','lesson-history-list');status.setAttribute('role','status');panel.append(status,list);
  async function draw(){
   const data=await api('account/lesson-history');list.replaceChildren();if(!data.items.length){list.append(node('p','muted','История пока пуста.'));return;}
   const labels={created:'Создана',saved:'Сохранённая версия',before_edit:'До изменения',edited:'Изменена',deleted:'Удалена',hidden:'Скрыта на дату',restored:'Восстановлена'};
   for(const entry of data.items){
    const item=node('article','admin-access-row lesson-history-entry'),body=entry.body;
    item.append(node('strong',null,body.title),node('p','muted',(labels[entry.action]||'Изменение')+' · '+(entry.created?new Date(entry.created).toLocaleString(uiLocale(),{timeZone:'Europe/Moscow'}):'Дата изменения не сохранена')),node('p','muted',dateLabel(entry.hidden_date||body.date)+' · '+body.start+(body.end?'–'+body.end:'')+(body.recurrence==='weekly'?' · Каждую неделю':'')+' · '+(entry.kind==='shared'||body.visibility==='group'?'Вся группа':'Только я')));
    for(const teacher of teacherNames(body)){const name=node('p','muted',teacher);name.dataset.personName='';item.append(name);}
    if(entry.can_restore)item.append(button(entry.active?'Вернуть эту версию':'Восстановить пару',async()=>{const result=await post('account/lesson-history/restore',{kind:entry.kind,id:entry.id});status.textContent=result.status==='pending'?'Отправлено администратору на подтверждение':'Пара восстановлена в расписании.';await load(true);await draw();}));
    list.append(item);
   }
  }
  panel.append(button('Обновить историю',draw));await draw();
 });
 details.dataset.tour='lesson-history';return details;
}
