/* Login button + dialog. Self-contained: it adds its own button to the top bar and its own dialog,
   so templates/index.html only needs <script src="/static/auth.js" defer></script>. */
(function () {
  const AUTH = (window.AUTH = { user: null, canEdit: false });
  const css = document.createElement('style');
  css.textContent =
    '#loginBtn{margin-left:2px;white-space:nowrap}' +
    '#loginDlg input[type=text],#loginDlg input[type=password]{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:8px;background:var(--panel2)}' +
    '#loginDlg{width:min(380px,94vw)}';
  document.head.appendChild(css);

  const btn = document.createElement('button');
  btn.id = 'loginBtn'; btn.type = 'button'; btn.className = 'btn sm'; btn.textContent = 'Log in';
  const theme = document.getElementById('themeBtn');
  (theme && theme.parentNode ? theme.parentNode : document.body).insertBefore(btn, theme);

  const dlg = document.createElement('dialog');
  dlg.id = 'loginDlg';
  dlg.innerHTML =
    '<form class="dlg" id="loginForm"><h2>Log in</h2><p>Needed to write changes to the sheets. Viewing stays open to everyone.</p>' +
    '<label for="lgUser">Username</label><input id="lgUser" type="text" autocomplete="username" required>' +
    '<label for="lgPass">Password</label><input id="lgPass" type="password" autocomplete="current-password" required>' +
    '<div class="row"><button class="btn primary" id="lgGo" type="submit">Log in</button>' +
    '<button class="btn" id="lgCancel" type="button">Cancel</button></div><div id="lgErr"></div></form>';
  document.body.appendChild(dlg);
  const $ = id => document.getElementById(id);

  function paint(user, canEdit) {
    AUTH.user = user || null; AUTH.canEdit = !!canEdit;
    btn.textContent = user ? 'Log out (' + user + ')' : 'Log in';
    btn.title = user ? 'Signed in as ' + user : 'Log in to write changes to the sheets';
    document.dispatchEvent(new CustomEvent('auth-changed', { detail: { user: AUTH.user, canEdit: AUTH.canEdit } }));
  }
  async function refresh() {
    try {
      const j = await (await fetch('/api/me')).json();
      paint(j.user, j.canEdit);
    } catch (e) { paint(null, false); }
  }

  btn.onclick = async () => {
    if (AUTH.user) {
      try { await fetch('/api/logout', { method: 'POST' }); } catch (e) { /* offline: the cookie expires anyway */ }
      paint(null, false);
    } else {
      $('lgErr').innerHTML = ''; $('lgPass').value = '';
      dlg.showModal(); $('lgUser').focus();
    }
  };
  $('lgCancel').onclick = () => dlg.close();
  $('loginForm').onsubmit = async ev => {
    ev.preventDefault();
    const go = $('lgGo'), err = $('lgErr');
    go.disabled = true; err.innerHTML = '';
    try {
      const r = await fetch('/api/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: $('lgUser').value, password: $('lgPass').value })
      });
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || 'Login failed');
      $('lgPass').value = ''; dlg.close(); await refresh();
    } catch (e) {
      const d = document.createElement('div'); d.className = 'err'; d.textContent = e.message;
      err.appendChild(d);
    } finally { go.disabled = false; }
  };
  refresh();
})();
