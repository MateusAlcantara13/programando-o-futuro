// ============================================================
// js/api.js — Central de comunicação com o back-end
// Programando o Futuro
// ============================================================

// ÚNICO ponto de configuração do endereço da API no front.
// Vazio quer dizer "mesma origem da página": o próprio backend serve o
// front, então '/api/...' funciona igual em local e em produção, sem editar
// arquivo. Só preencha se um dia o front for servido de outro endereço, e
// nesse caso a origem do front precisa entrar em CORS_ORIGENS no backend.
// Outras páginas (admin, mapa) usam esta mesma constante.
const API_URL = '';

// ── Armazenamento ──────────────────────────────────────────
// Os alunos usam computadores compartilhados da escola. Por isso tudo do
// sistema (chaves 'pf_*') fica em sessionStorage, que some quando o
// navegador fecha, e nunca em localStorage, que fica para o próximo aluno.
// Nenhuma senha é guardada em lugar nenhum: só o token e os dados públicos
// do perfil que o backend devolve.
const PREFIXO_ARMAZENAMENTO = 'pf_';

function limparChavesPf(storage) {
  try {
    Object.keys(storage)
      .filter((chave) => chave.startsWith(PREFIXO_ARMAZENAMENTO))
      .forEach((chave) => storage.removeItem(chave));
  } catch (e) {}
}

// Versões antigas gravavam token, perfil e rascunhos de resposta em
// localStorage. Apaga o que tiver sobrado na máquina.
limparChavesPf(localStorage);

// ── Token helpers ──────────────────────────────────────────
const auth = {
  getToken:  ()      => sessionStorage.getItem('pf_token'),
  setToken:  (t)     => sessionStorage.setItem('pf_token', t),
  getUser:   ()      => JSON.parse(sessionStorage.getItem('pf_user') || 'null'),
  setUser:   (u)     => sessionStorage.setItem('pf_user', JSON.stringify(u)),
  // Apaga tudo do sistema, inclusive rascunhos de resposta, para o próximo
  // aluno na mesma máquina não ver nada do anterior.
  clear:     ()      => { limparChavesPf(sessionStorage); limparChavesPf(localStorage); },
  isLogged:  ()      => !!sessionStorage.getItem('pf_token'),
};

// ── Sessão encerrada ───────────────────────────────────────
const CHAVE_AVISO_LOGIN = 'pf_aviso_login';

function mensagemSessaoEncerrada(erro) {
  const codigo = erro?.detail?.codigo;
  return codigo === 'TOKEN_EXPIRADO'
    ? 'Sua sessão expirou. Entre de novo para continuar.'
    : 'Sua sessão terminou. Entre de novo para continuar.';
}

// Limpa a sessão e leva para o login com o motivo, em vez de deixar a tela quebrada.
function encerrarSessao(erro) {
  auth.clear();
  sessionStorage.setItem(CHAVE_AVISO_LOGIN, mensagemSessaoEncerrada(erro));
  window.location.href = pagePath('login.html');
}

// Usado pela tela de login para mostrar o motivo uma vez só.
function lerAvisoLogin() {
  const aviso = sessionStorage.getItem(CHAVE_AVISO_LOGIN);
  sessionStorage.removeItem(CHAVE_AVISO_LOGIN);
  return aviso;
}

// ── Fetch base ─────────────────────────────────────────────
async function apiFetch(path, options = {}) {
  const { skipAuthRedirect = false, ...fetchOptions } = options;
  const token = auth.getToken();
  const headers = { 'Content-Type': 'application/json', ...(fetchOptions.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}${path}`, { ...fetchOptions, headers });

  let data = {};
  try { data = await res.json(); } catch (e) {}

  if (res.status === 401 && !path.startsWith('/api/auth/') && !skipAuthRedirect) {
    encerrarSessao(data);
    return;
  }

  if (!res.ok) throw { status: res.status, ...data };
  return data;
}

function determinarLoginPath() {
  // Descobre se está em /pages/ ou na raiz
  return homePath();
}

function pagePath(pageName) {
  return window.location.pathname.includes('/pages/') ? pageName : `pages/${pageName}`;
}

function homePath() {
  return window.location.pathname.includes('/pages/') ? '../index.html' : 'index.html';
}

function destinoUsuario(usuario = auth.getUser()) {
  return usuario?.teste_inicial_concluido
    ? pagePath('inicial_mapa_feito.html')
    : pagePath('inicial_logada.html');
}

async function redirecionarUsuarioLogado({ silencioso = false } = {}) {
  if (!auth.isLogged()) return false;

  try {
    const usuario = await authApi.me({ skipAuthRedirect: true });
    auth.setUser(usuario);
    window.location.href = destinoUsuario(usuario);
    return true;
  } catch (error) {
    if (error?.status === 401 && !silencioso) {
      encerrarSessao(error);
      return false;
    }
    auth.clear();
    if (!silencioso) window.location.href = determinarLoginPath();
    return false;
  }
}

async function protegerPagina({ precisaMapaFeito = null } = {}) {
  if (!auth.isLogged()) {
    window.location.href = homePath();
    return false;
  }

  try {
    const usuario = await authApi.me({ skipAuthRedirect: true });
    auth.setUser(usuario);

    if (precisaMapaFeito === true && !usuario.teste_inicial_concluido) {
      window.location.href = pagePath('inicial_logada.html');
      return false;
    }

    if (precisaMapaFeito === false && usuario.teste_inicial_concluido) {
      window.location.href = pagePath('inicial_mapa_feito.html');
      return false;
    }

    return usuario;
  } catch (error) {
    if (error?.status === 401) {
      encerrarSessao(error);
      return false;
    }
    auth.clear();
    window.location.href = homePath();
    return false;
  }
}

// ── API methods ────────────────────────────────────────────
const api = {
  get:    (path)        => apiFetch(path),
  post:   (path, body)  => apiFetch(path, { method: 'POST',  body: JSON.stringify(body) }),
  patch:  (path, body)  => apiFetch(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: (path)        => apiFetch(path, { method: 'DELETE' }),
};

// ── Auth calls ─────────────────────────────────────────────
const authApi = {
  // aceiteLgpd vem da caixa que o aluno marcou; versaoTermo é a versão do
  // termo que a tela mostrou (GET /api/lgpd/termo). O backend recusa se o
  // aceite não for true ou se a versão não for a atual.
  async cadastro(nome, email, senha, aceiteLgpd, versaoTermo) {
    // aceite_menor não é enviado: nenhuma tela coleta o consentimento dos
    // responsáveis ainda (pendência no ROADMAP), e o backend grava NULL.
    const data = await api.post('/api/auth/cadastro', {
      nome, email, senha,
      aceite_lgpd: aceiteLgpd === true,
      versao_termo_lgpd: versaoTermo
    });
    auth.setToken(data.token);
    auth.setUser(data.usuario);
    return data;
  },

  async login(email, senha) {
    const data = await api.post('/api/auth/login', { email, senha });
    auth.setToken(data.token);
    auth.setUser(data.usuario);
    return data;
  },

  me(options = {}) {
    return apiFetch('/api/auth/me', { skipAuthRedirect: options.skipAuthRedirect });
  },

  atualizarPerfil: (dados) => api.patch('/api/auth/perfil', dados),

  logout() {
    auth.clear();
    window.location.href = determinarLoginPath();
  }
};

// ── Teste inicial ──────────────────────────────────────────
const testeApi = {
  perguntas:  ()             => api.get('/api/testeinicial/perguntas'),
  progresso:  ()             => api.get('/api/testeinicial/progresso'),
  respostasDestaque: (limite = 3, aleatorio = true) =>
  api.get(`/api/testeinicial/respostas/destaque?limite=${limite}&aleatorio=${aleatorio}`),
  salvarResposta: (perguntaId, valor, textoLivre = '') =>
    api.patch('/api/testeinicial/resposta', { perguntaId: String(perguntaId), valor, textoLivre }),
  finalizar: (respostas)     => api.post('/api/testeinicial/finalizar', { respostas }),
  status:    (jobId)         => api.get(`/api/resultado/status?jobId=${jobId}`),
  resultado: ()              => api.get('/api/resultado'),
};

// ── Módulos ────────────────────────────────────────────────
const modulosApi = {
  listar:         ()              => api.get('/api/modulos'),
  perguntas:      (id)            => api.get(`/api/modulos/${id}/perguntas`),
  progresso:      (id)            => api.get(`/api/modulos/${id}/progresso`),
  salvarResposta: (id, perguntaId, valor, textoLivre = '') =>
    api.patch(`/api/modulos/${id}/resposta`, { perguntaId: String(perguntaId), valor, textoLivre }),
  finalizar:      (id)            => api.post(`/api/modulos/${id}/finalizar`, {}),
};

// ── Perfil / Mapa / Jornada ────────────────────────────────
const perfilApi = {
  get:            ()  => api.get('/api/perfil'),
  mapa:           ()  => api.get('/api/mapa'),
  jornadaProgresso: () => api.get('/api/jornada/progresso'),
};

// ── UI helpers ─────────────────────────────────────────────
function showErro(msg, containerId = 'erroMsg') {
  let el = document.getElementById(containerId);
  if (!el) {
    el = document.createElement('div');
    el.id = containerId;
    el.className = 'auth-alert';
    el.setAttribute('role', 'alert');

    const authCard = document.querySelector('.auth-card');
    if (authCard) {
      authCard.prepend(el);
    } else {
      document.querySelector('.question-wrap, main')?.appendChild(el);
    }
  }
  el.textContent = msg;
  el.style.display = 'block';
}

function hideErro(containerId = 'erroMsg') {
  const el = document.getElementById(containerId);
  if (el) el.style.display = 'none';
}

function setLoading(btnEl, loading, textoOriginal) {
  if (loading) {
    btnEl.disabled = true;
    btnEl.style.opacity = '0.6';
    btnEl.textContent = 'Aguarde...';
  } else {
    btnEl.disabled = false;
    btnEl.style.opacity = '1';
    btnEl.innerHTML = textoOriginal;
  }
}

// ── Guard: redireciona se não logado ──────────────────────
function requireAuth() {
  return protegerPagina();
}

// ── Botão de sair ──────────────────────────────────────────
// Fixo e sempre visível em toda tela de aluno logado, inclusive nas que não
// têm menu lateral. Limpa o armazenamento e volta para a tela inicial.
const PAGINAS_SEM_BOTAO_SAIR = ['login.html', 'cadastro.html', 'admin.html'];

function montarBotaoSair() {
  const pagina = window.location.pathname.split('/').pop();
  if (!window.location.pathname.includes('/pages/')) return;
  if (PAGINAS_SEM_BOTAO_SAIR.includes(pagina)) return;
  if (!auth.isLogged() || document.getElementById('pfBotaoSair')) return;

  const botao = document.createElement('button');
  botao.id = 'pfBotaoSair';
  botao.type = 'button';
  botao.textContent = 'Sair';
  botao.setAttribute('aria-label', 'Sair da conta');
  botao.style.cssText = [
    'position:fixed', 'right:16px', 'bottom:16px', 'z-index:9999',
    'padding:0.55rem 1.1rem', 'border-radius:999px', 'cursor:pointer',
    'font:600 0.85rem sans-serif', 'color:#fca5a5',
    'background:rgba(17,17,27,0.9)', 'border:1px solid rgba(220,38,38,0.4)',
  ].join(';');
  botao.addEventListener('click', () => authApi.logout());
  document.body.appendChild(botao);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', montarBotaoSair);
} else {
  montarBotaoSair();
}

// ── Botão Voltar depois de sair ────────────────────────────
// O navegador pode guardar a página inteira em memória (bfcache) e mostrá-la
// de novo no Voltar, sem recarregar, com os dados do aluno que acabou de
// sair. Se a página voltou assim e não há mais sessão, sai dela.
window.addEventListener('pageshow', (evento) => {
  if (!evento.persisted) return;
  const pagina = window.location.pathname.split('/').pop();
  if (!window.location.pathname.includes('/pages/')) return;
  if (PAGINAS_SEM_BOTAO_SAIR.includes(pagina)) return;
  if (!auth.isLogged()) window.location.replace(homePath());
});
