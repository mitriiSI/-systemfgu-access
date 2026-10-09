/* Personal subject branches apply to the diary and every reminder channel. */
function subgroupHint(host){
 const pending=(scheduleInfo.subgroups||[]).filter(subject=>!subject.selected);
 if(!pending.length)return;
 const hint=button('Выберите свою подгруппу ›',()=>go('profile'),'onboarding-hint');
 hint.setAttribute('aria-label','Выбрать подгруппу: '+pending.map(subject=>subject.title).join(', '));host.append(hint);
}
function scheduleStatus(host){
 if(!scheduleInfo.error&&(!scheduleInfo.syncing||days.length))return;
 const status=node('details','schedule-status');status.append(node('summary',null,scheduleInfo.syncing?'Проверяем обновления расписания…':'Часть расписания не удалось обновить. Сохранённые занятия доступны.'));
 if(scheduleInfo.error)status.append(node('p','muted','Обновление выполняется автоматически. Если соединение восстановилось, можно повторить проверку.'),button('Повторить обновление',async()=>{await post('schedule/refresh',{});await load(true);await go('day',false);}));
 host.append(status);
}
async function subgroupSettings(host){
 const section=node('section','subgroup-settings');section.dataset.tour='subgroups';
 section.append(node('h2',null,'Мои подгруппы'),node('p','muted','Выберите преподавателя или подгруппу для разделённых занятий. Общие лекции остаются у всех; выбор учитывается в дневнике и напоминаниях.'));host.append(section);
 const data=await api('schedule/subgroups');if(!host.isConnected)return;
 if(!data.subjects.length){section.append(node('p','muted','Когда в расписании появятся разделённые занятия, здесь можно будет выбрать свою подгруппу.'));return;}
 const form=node('form','subgroup-form'),fields=new Map();section.append(form);
 for(const subject of data.subjects){
  const select=selectField(form,subjectDisplay(subject.title));option(select,'','Показывать все подгруппы');
  subject.options.forEach(entry=>option(select,entry.id,entry.label));select.value=subject.selected;fields.set(subject.subject,select);
 }
 const save=node('button','fd-primary','Сохранить мои подгруппы'),status=node('p','muted');save.type='submit';status.setAttribute('role','status');form.append(save,status);
 form.onsubmit=async event=>{event.preventDefault();save.disabled=true;form.dataset.dirty='true';try{
  const result=await post('schedule/subgroups',{choices:Object.fromEntries([...fields].map(([subject,input])=>[subject,input.value]))});
  scheduleInfo.subgroups=result.subjects;await load(true);status.textContent='Подгруппы сохранены. Дневник и напоминания учитывают ваш выбор.';delete form.dataset.dirty;
 }catch(error){status.textContent=error.message;}finally{save.disabled=false;}};
}
