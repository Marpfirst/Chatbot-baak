let sessionId = ""; // diisi dari respons pertama
const chatLog = document.getElementById('chat-log');
const input = document.getElementById('chat-input');
const form = document.getElementById('chat-form');
const btnSend = document.getElementById('btn-send');
const btnNew = document.getElementById('btn-newchat');
const btnHealth = document.getElementById('btn-health');
const pill = document.getElementById('session-pill');

function scrollToBottom(){
  requestAnimationFrame(() => { chatLog.scrollTop = chatLog.scrollHeight; });
}
function truncateId(id){ return id ? id.slice(0,8) + '…' : ''; }
function setSession(id){
  if (!id) return;
  sessionId = id;
  pill.textContent = 'session: ' + truncateId(id);
  pill.classList.remove('hidden');
}
function mdToHtml(md){
  try { return marked.parse(md || ''); } catch(e){
    return (md || '').replace(/\n/g,'<br>');
  }
}
function escapeHtml(s){
  return (s||'').replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;','\'':'&#39;'}[c]));
}

function bubbleUser(text){
  const wrap = document.createElement('div');
  wrap.className = 'flex items-start gap-3 justify-end fade-in';
  const timeStr = ChatTime.formatTime(new Date());
  wrap.innerHTML = `
    <div class="bubble bg-indigo-600 text-white p-3 md:p-4 max-w-[80%] shadow-soft">
      <div class="text-[13px] text-indigo-100 mb-1 text-right">Anda</div>
      <div class="prose prose-sm prose-invert">${mdToHtml(escapeHtml(text))}</div>
      <div class="meta-row">
        <span class="msg-time">${timeStr}</span>
      </div>
    </div>`;
  chatLog.appendChild(wrap);
  scrollToBottom();
}

function bubbleBot(answer, meta){
  const wrap = document.createElement('div');
  wrap.className = 'flex items-start gap-3 fade-in';
  const timeStr = ChatTime.formatTime(new Date());
  wrap.innerHTML = `
    <div class="h-8 w-8 grid place-content-center rounded-full bg-indigo-600 text-white text-sm">BA</div>
    <div class="bubble bg-white p-3 md:p-4 shadow-soft max-w-[80%]">
      <div class="text-[13px] text-gray-500 mb-1">BAAK Bot</div>
      <div class="prose prose-sm text-gray-800">${mdToHtml(answer)}</div>
      <div class="meta-row">
        ${meta && meta.source ? `<span class="badge">src: ${escapeHtml(meta.source||'-')}</span>` : ''}
        ${meta && meta.intent ? `<span class="badge">intent: ${escapeHtml(meta.intent||'-')}</span>` : ''}
        ${meta && typeof meta.has_data === 'boolean' ? `<span class="badge">${meta.has_data ? 'has_data' : 'no_data'}</span>` : ''}
        <span class="msg-time">${timeStr}</span>
      </div>
    </div>`;
  chatLog.appendChild(wrap);
  scrollToBottom();
}

function bubbleTyping(){
  const wrap = document.createElement('div');
  wrap.className = 'flex items-start gap-3 fade-in';
  wrap.id = 'typing';
  wrap.innerHTML = `
    <div class="h-8 w-8 grid place-content-center rounded-full bg-indigo-600 text-white text-sm">BA</div>
    <div class="bubble bg-white p-3 md:p-4 shadow-soft max-w-[80%]">
      <div class="text-[13px] text-gray-500 mb-1">BAAK Bot</div>
      <div class="flex items-center gap-2 text-gray-500"><span class="animate-pulse">•••</span> menulis…</div>
      <div class="meta-row">
        <span class="msg-time">${ChatTime.formatTime(new Date())}</span>
      </div>
    </div>`;
  chatLog.appendChild(wrap);
  scrollToBottom();
}
function removeTyping(){
  const t = document.getElementById('typing');
  if (t) t.remove();
}

async function send(text){
  if (!text.trim()) return;
  bubbleUser(text);
  input.value = '';
  input.style.height = 'auto';

  bubbleTyping();
  btnSend.disabled = true;

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: text, session_id: sessionId || '' })
    });
    const data = await res.json();
    removeTyping();
    setSession(data.session_id);
    bubbleBot(data.answer || '(jawaban kosong)', {
      source: data.source, intent: data.intent, has_data: !!data.has_data
    });
  } catch (e){
    removeTyping();
    bubbleBot('❌ Gagal menghubungi server. Pastikan backend FastAPI berjalan di port yang sama.', { source:'client', intent:'error', has_data:false });
  } finally {
    btnSend.disabled = false;
  }
}

form.addEventListener('submit', (ev) => {
  ev.preventDefault();
  send(input.value);
});
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey){
    e.preventDefault();
    send(input.value);
  }
});
input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 200) + 'px';
});

btnNew.addEventListener('click', async () => {
  if (!sessionId){
    location.reload();
    return;
  }
  try{
    await fetch('/api/session/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId })
    });
  }catch(e){}
  location.reload();
});

btnHealth.addEventListener('click', async () => {
  try {
    const res = await fetch('/api/health');
    const h = await res.json();
    bubbleBot('**Health Check**\n\n' +
      `• Status: ${h.status}\n` +
      `• Sessions: ${h.active_sessions}\n` +
      `• Pinecone: ${h.pinecone_status} (vectors: ${h.pinecone_vectors})\n` +
      `• DB: ${h.db_status}`,
      { source:'system', intent:'health', has_data:true }
    );
  } catch(e){
    bubbleBot('Tidak bisa memanggil /api/health', { source:'client', intent:'error', has_data:false });
  }
});

// Quick ask dari tombol contoh
window.quickAsk = (q) => { send(q); };
