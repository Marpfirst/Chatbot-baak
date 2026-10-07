(function(){
  // ganti ke "12h" kalau mau 1:05 PM
  const TIME_FORMAT = "24h";

  function formatTime(date){
    const d = (date instanceof Date) ? date : new Date(date);
    if (TIME_FORMAT === "12h") {
      let h = d.getHours(), m = String(d.getMinutes()).padStart(2,'0');
      const suf = h >= 12 ? 'PM' : 'AM';
      h = h % 12 || 12;
      return `${h}:${m} ${suf}`;
    }
    const hh = String(d.getHours()).padStart(2,'0');
    const mm = String(d.getMinutes()).padStart(2,'0');
    return `${hh}:${mm}`;
  }

  window.ChatTime = { formatTime, TIME_FORMAT };
})();
