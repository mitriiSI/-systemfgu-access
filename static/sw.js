self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  if (event.request.mode !== 'navigate') return;
  event.respondWith(fetch(event.request).catch(() => new Response(
    "<!doctype html><html lang=\"ru\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Midiary</title><body style=\"font:18px system-ui;padding:28px;background:#09090b;color:white\"><h1 id=\"title\">Нет соединения</h1><p id=\"message\">Проверьте интернет. Ваши записи хранятся на сервере.</p><button id=\"retry\" onclick=\"location.reload()\">Повторить</button><script>const l=localStorage.getItem('midiary-language')||'ru',copy={en:['No connection','Check your internet connection. Your notes are stored on the server.','Retry'],zh:['没有连接','请检查网络连接。你的笔记保存在服务器上。','重试']};if(copy[l]){document.documentElement.lang=l;['title','message','retry'].forEach((id,i)=>document.getElementById(id).textContent=copy[l][i]);}</script></body></html>",
    {headers: {'Content-Type': 'text/html; charset=utf-8'}}
  )));
});


self.addEventListener('push',event=>{
 let data={};try{data=event.data?.json()||{};}catch{}
 const title=typeof data.title==='string'?data.title:'Midiary';
 event.waitUntil(self.registration.showNotification(title,{body:typeof data.body==='string'?data.body:'Откройте дневник, чтобы посмотреть обновление.',icon:'/static/midiary-icon-192.png',badge:'/static/midiary-icon-192.png',tag:typeof data.tag==='string'?data.tag:'fgu-update',data:{url:safePushUrl(data.url)}}));
});
function safePushUrl(value){
 try{const url=new URL(value||'/',self.location.origin);if(url.origin===self.location.origin&&url.pathname==='/')return url.href;}catch{}
 return self.location.origin+'/';
}
self.addEventListener('notificationclick',event=>{
 event.notification.close();const url=safePushUrl(event.notification.data?.url);
 event.waitUntil((async()=>{
  const windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});
  for(const client of windows){if(new URL(client.url).origin===self.location.origin){try{const navigated=await client.navigate(url);await (navigated||client).focus();return;}catch{}}}
  await self.clients.openWindow(url);
 })());
});
