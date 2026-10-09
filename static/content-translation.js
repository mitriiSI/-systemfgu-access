const contentTranslations=new Map(),contentTranslationQueue=new Map(),contentTranslationRetry=new Map();
let contentTranslationTimer=null,contentTranslationBusy=false,contentTranslationOwner='';
function translationKey(text){return uiLanguage()+'|'+text;}
function translateDynamicText(source){
 if(uiLanguage()==='ru'||!/[А-Яа-яЁё]/.test(source)||source.length>4000)return null;
 if(typeof me==='undefined'||!me||me.needs_group)return null;
 const key=translationKey(source);
 const owner=me.code||String(me.tg);if(owner!==contentTranslationOwner){contentTranslations.clear();contentTranslationQueue.clear();contentTranslationRetry.clear();contentTranslationOwner=owner;}
 if(contentTranslations.has(key))return contentTranslations.get(key);
 if((contentTranslationRetry.get(key)||0)>Date.now())return null;
 contentTranslationQueue.set(key,source);scheduleContentTranslation();return null;
}
function scheduleContentTranslation(){if(!contentTranslationTimer&&!contentTranslationBusy)contentTranslationTimer=setTimeout(flushContentTranslation,180);}
async function flushContentTranslation(){
 contentTranslationTimer=null;if(contentTranslationBusy||!contentTranslationQueue.size||!me)return;
 const owner=contentTranslationOwner,language=uiLanguage();let length=0;
 const entries=[...contentTranslationQueue].filter(([key])=>key.startsWith(language+'|')).filter(([,text])=>{if(length+text.length>12000)return false;length+=text.length;return true;}).slice(0,24);
 if(!entries.length)return;contentTranslationBusy=true;for(const [key] of entries)contentTranslationQueue.delete(key);
 try{
  const result=await post('translate-titles',{language,texts:entries.map(([,text])=>text)});
  if(owner!==contentTranslationOwner)return;
  entries.forEach(([key],index)=>{const value=result.translations[index];if(typeof value==='string')contentTranslations.set(key,value);else contentTranslationRetry.set(key,Date.now()+(result.available?2500:60000));});
  if(result.available&&result.pending)setTimeout(translateInterface,2700);
  translateInterface();
 }catch{for(const [key] of entries)contentTranslationRetry.set(key,Date.now()+60000);}
 finally{contentTranslationBusy=false;if(contentTranslationQueue.size)scheduleContentTranslation();}
}
function transliterateName(name){
 if(uiLanguage()==='ru')return name;
 const letters={'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'yo','ж':'zh','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'shch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'};
 return [...name].map(letter=>{const value=letters[letter.toLowerCase()];return value===undefined?letter:letter!==letter.toLowerCase()?value.charAt(0).toUpperCase()+value.slice(1):value;}).join('');
}

function personNameNode(name){const element=node('strong',null,name);element.dataset.personName='';return element;}
