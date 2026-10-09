// Runs document parsing off the UI thread so Close remains responsive.
const escapeText=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
function imageData(image){
 if(!image||!['image/png','image/jpeg','image/gif','image/webp'].includes(image.mime)||image.bytes.length>8*1024*1024)return '';
 let data='';for(let i=0;i<image.bytes.length;i+=8192)data+=String.fromCharCode(...image.bytes.subarray(i,i+8192));
 return '<img alt="Изображение из документа" src="data:'+image.mime+';base64,'+btoa(data)+'">';
}
function wordModelHtml(paragraphs){
 let html='',row=[],rows=[];
 const flushTable=()=>{if(row.length){rows.push(row);row=[];}if(rows.length){html+='<table><tbody>'+rows.map(cells=>'<tr>'+cells.map(cell=>'<td>'+cell+'</td>').join('')+'</tr>').join('')+'</tbody></table>';rows=[];}};
 for(const paragraph of paragraphs||[]){
  let text='';for(const run of paragraph.runs||[]){
   if(run.image){text+=imageData(run.image);continue;}
   let value=escapeText(run.text);if(run.b)value='<strong>'+value+'</strong>';if(run.i)value='<em>'+value+'</em>';if(run.u)value='<u>'+value+'</u>';if(run.strike)value='<s>'+value+'</s>';
   if(run.va==='super')value='<sup>'+value+'</sup>';if(run.va==='sub')value='<sub>'+value+'</sub>';text+=value;
  }
  if(paragraph.kind==='cell'||paragraph.kind==='rowEnd'){row.push(text);if(paragraph.kind==='rowEnd'){rows.push(row);row=[];}continue;}
  flushTable();const align=['left','center','right','justify'][paragraph.align]||'left';
  html+='<p style="text-align:'+align+'">'+text+'</p>';
 }flushTable();return html;
}
function decodeText(bytes){
 if(bytes[0]===255&&bytes[1]===254)return new TextDecoder('utf-16le').decode(bytes);
 if(bytes[0]===254&&bytes[1]===255)return new TextDecoder('utf-16be').decode(bytes);
 const head=new TextDecoder().decode(bytes.subarray(0,4096));const charset=head.match(/charset\s*=\s*["']?([\w-]+)/i)?.[1];
 if(charset){try{return new TextDecoder(charset).decode(bytes);}catch{}}
 try{return new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch{return new TextDecoder('windows-1251').decode(bytes);}
}
// Some files named .doc are RTF. Read their text without executing fields or objects.
function rtfText(bytes){
 let text='';for(let i=0;i<bytes.length;i+=8192)text+=String.fromCharCode(...bytes.subarray(i,i+8192));
 const stack=[];let state={skip:false,uc:1,encoding:'windows-1252'},fallback=0,out='';
 const ignored=new Set(['fonttbl','colortbl','stylesheet','info','pict','object','objdata','fldinst','filetbl','listtable','listoverridetable','generator','datastore','themedata','xmlnstbl','header','footer']);
 function emit(value){if(fallback>0){fallback--;return;}if(!state.skip)out+=value;}
 for(let i=0;i<text.length;){
  let ch=text[i++];if(ch==='{'){stack.push({...state});continue;}if(ch==='}'){state=stack.pop()||state;continue;}
  if(ch!=='\\'){if(ch!=='\r'&&ch!=='\n')emit(ch.charCodeAt(0)>127?new TextDecoder(state.encoding).decode(Uint8Array.of(ch.charCodeAt(0))):ch);continue;}
  ch=text[i++];if(ch==='*'){state.skip=true;continue;}if(['\\','{','}'].includes(ch)){emit(ch);continue;}
  if(ch==="'"){const value=parseInt(text.slice(i,i+2),16);i+=2;if(Number.isFinite(value))emit(new TextDecoder(state.encoding).decode(Uint8Array.of(value)));continue;}
  if(ch==='~'){emit('\u00a0');continue;}if(ch==='-')continue;
  if(!/[a-z]/i.test(ch||''))continue;
  let word=ch;while(i<text.length&&/[a-z]/i.test(text[i]))word+=text[i++];
  let number='';if(text[i]==='-')number+=text[i++];while(i<text.length&&/\d/.test(text[i]))number+=text[i++];if(text[i]===' ')i++;
  const value=Number(number);if(ignored.has(word)){state.skip=true;continue;}
  if(word==='bin'){i+=Math.max(0,value);continue;}
  if(word==='ansicpg'){try{new TextDecoder('windows-'+value);state.encoding='windows-'+value;}catch{}continue;}
  if(word==='uc'){state.uc=Math.max(0,Math.min(value,10));continue;}
  if(word==='u'){fallback=0;emit(String.fromCharCode((value+65536)%65536));fallback=state.uc;continue;}
  if(['par','line','row'].includes(word))emit('\n');else if(['tab','cell'].includes(word))emit('\t');
  else if(word==='emdash')emit('—');else if(word==='endash')emit('–');else if(word==='bullet')emit('•');
 }return out;
}
self.onmessage=async event=>{
 try{
  const bytes=new Uint8Array(event.data.bytes);let html='',kind='word';
  if(bytes[0]===0x50&&bytes[1]===0x4b){
   importScripts('/static/vendor/documents/mammoth.browser.min.js');
   const result=await mammoth.convertToHtml({arrayBuffer:bytes.buffer},{externalFileAccess:false,includeDefaultStyleMap:true,convertImage:mammoth.images.imgElement(async image=>{
    if(!['image/png','image/jpeg','image/gif','image/webp'].includes(image.contentType))return {alt:'Изображение в неподдерживаемом формате'};
    const data=await image.read('base64');if(data.length>12*1024*1024)return {alt:'Большое изображение'};
    return {src:'data:'+image.contentType+';base64,'+data};
   })});html=result.value;kind='docx';
  }else if(bytes[0]===0xd0&&bytes[1]===0xcf){
   importScripts('/static/vendor/documents/docToText.js');
   const model=docToText.model(bytes);if(!model)throw Error('Этот DOC повреждён, защищён паролем или создан в слишком старой версии Word.');
   html=wordModelHtml(model.body);
   for(const [key,label] of [['footnotes','Сноски'],['endnotes','Концевые сноски'],['textboxes','Текстовые блоки'],['headers','Колонтитулы'],['headerTextboxes','Текст колонтитулов']]){
    if(model[key]?.some(p=>p.runs?.some(r=>r.text||r.image)))html+='<h2>'+label+'</h2>'+wordModelHtml(model[key]);
   }kind='doc';
  }else{
   const text=decodeText(bytes);
   if(/^\s*{\\rtf/i.test(text)){html='<pre>'+escapeText(rtfText(bytes))+'</pre>';kind='rtf';}
   else if(/<(!doctype|html|head|body|p[\s>]|table[\s>])/i.test(text.slice(0,4096))){html=text;kind='html';}
   else if(!text.includes('\u0000')){html='<pre>'+escapeText(text)+'</pre>';kind='text';}
   else throw Error('Не удалось прочитать этот формат документа.');
  }
  if(html.length>16*1024*1024)throw Error('Документ слишком большой для просмотра на этом устройстве.');
  self.postMessage({ok:true,html,kind});
 }catch(error){self.postMessage({ok:false,error:error.message||'Не удалось прочитать документ.'});}
};
