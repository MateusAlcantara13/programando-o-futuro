(function () {
  const path = window.location.pathname;
  const moduloMatch = path.match(/modulo(\d+)\.html$/);
  const isTesteInicial = path.endsWith('/perguntas.html') || path.endsWith('\\perguntas.html');
  const moduloId = moduloMatch ? String(moduloMatch[1]).padStart(2, '0') : null;
  const storageKey = isTesteInicial ? 'pf_respostas_teste_api' : `pf_modulo_${moduloId}_api`;

  let perguntas = [];
  let currentQ = 1;
  let respostas = {};
  let enviando = false;

  const params = new URLSearchParams(window.location.search);
  const qParam = parseInt(params.get('q'), 10);

  // ── Blocos do teste inicial ────────────────────────────────────────────────
  // As perguntas do teste inicial trazem o campo "bloco". As dos módulos não
  // trazem, e as páginas dos módulos não têm a barra segmentada: lá o modo
  // blocos fica desligado e tudo funciona como antes.
  //
  // Texto da tela de transição mostrada ANTES de cada bloco, a partir do
  // segundo. A chave é o nome do bloco exatamente como vem da API. Bloco sem
  // texto aqui ganha a tela só com o nome.
  const TEXTOS_BLOCO = {
    'Sua situação financeira':
      'Agora algumas perguntas sobre dinheiro e estrutura: renda da família, trabalho, mensalidade e acesso a computador e internet. Ninguém aqui está te avaliando. Com isso o plano mostra bolsas, financiamentos e cursos gratuitos que cabem na sua realidade.',
    'Onde você quer chegar':
      'Hora de falar do que você quer: até onde consegue se deslocar, em quanto tempo quer trabalhar na sua área e o que pesa mais para você. É assim que o plano decide quais caminhos entram e em que ordem.',
    'Quem você é por dentro':
      'Agora é sobre o seu jeito: o que você faz por conta própria, como encara um problema e onde se sai bem. Não tem resposta certa. Responda o que é verdade para você, porque é daqui que saem as áreas que combinam com você.',
    'Seu contexto de vida':
      'Falta pouco. Estas perguntas olham para o que você já viveu fora da escola, para o que te trava na hora de escolher e para a sua abertura a caminhos novos. Assim o plano começa de onde você está hoje.',
  };

  let blocos = [];          // [{ nome, inicio, fim }], índices a partir de 0
  let modoBlocos = false;
  let navegando = false;    // impede clique duplo durante a animação
  const reduzirMovimento = window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)')
    : null;

  function montarBlocos() {
    blocos = [];
    perguntas.forEach((q, i) => {
      const ultimo = blocos[blocos.length - 1];
      if (ultimo && ultimo.nome === q.bloco) ultimo.fim = i;
      else blocos.push({ nome: q.bloco, inicio: i, fim: i });
    });
    modoBlocos = Boolean(document.getElementById('progressSegments'))
      && perguntas.length > 0
      && perguntas.every((q) => q.bloco);
  }

  // n começa em 1, como currentQ.
  function blocoDaPergunta(n) {
    const i = n - 1;
    const indice = blocos.findIndex((b) => i >= b.inicio && i <= b.fim);
    const b = blocos[indice];
    return { indice, nome: b.nome, posicao: i - b.inicio + 1, tamanho: b.fim - b.inicio + 1 };
  }

  function renderProgressoBlocos(indiceAtual, fracaoAtual) {
    const wrap = document.getElementById('progressSegments');
    if (wrap.children.length !== blocos.length) {
      wrap.innerHTML = '';
      blocos.forEach((b) => {
        const seg = document.createElement('div');
        seg.className = 'progress-segment';
        seg.title = b.nome;
        const fill = document.createElement('div');
        fill.className = 'progress-segment-fill';
        seg.appendChild(fill);
        wrap.appendChild(seg);
      });
    }
    Array.from(wrap.children).forEach((seg, i) => {
      seg.classList.toggle('feito', i < indiceAtual);
      seg.classList.toggle('atual', i === indiceAtual);
      const fracao = i < indiceAtual ? 1 : (i === indiceAtual ? fracaoAtual : 0);
      seg.firstChild.style.width = `${Math.round(fracao * 100)}%`;
    });
    wrap.setAttribute('aria-valuemin', '0');
    wrap.setAttribute('aria-valuemax', String(blocos.length));
    wrap.setAttribute('aria-valuenow', String(indiceAtual + fracaoAtual));
    wrap.setAttribute('aria-valuetext', `Parte ${indiceAtual + 1} de ${blocos.length}: ${blocos[indiceAtual].nome}`);
  }

  function mostrarIntroBloco(indice) {
    const b = blocos[indice];
    document.getElementById('questionCard').hidden = true;
    document.getElementById('blockIntro').hidden = false;
    // "2/5" grande na tela; o leitor de tela recebe "Parte 2 de 5".
    // Só números entram no HTML.
    document.getElementById('blockIntroEyebrow').innerHTML =
      `<span class="parte-atual" aria-hidden="true">${indice + 1}</span>`
      + `<span class="parte-total" aria-hidden="true">/${blocos.length}</span>`
      + `<span class="sr-only">Parte ${indice + 1} de ${blocos.length}</span>`;
    document.getElementById('blockIntroTitle').textContent = b.nome;
    document.getElementById('blockIntroText').textContent = TEXTOS_BLOCO[b.nome] || '';
    renderProgressoBlocos(indice, 0);
    document.getElementById('blockIntroContinuar').focus();
  }

  // Saída curta, troca o conteúdo, entrada curta: 110 + 150 = 260 ms no total.
  // Sem animação com prefers-reduced-motion ou fora do modo blocos.
  async function trocarTela(trocar, direcao) {
    const wrap = document.querySelector('.question-wrap');
    const semAnimacao = !modoBlocos || !wrap || typeof wrap.animate !== 'function'
      || (reduzirMovimento && reduzirMovimento.matches);
    if (semAnimacao) {
      trocar();
      return;
    }
    const d = direcao === 'tras' ? -1 : 1;
    navegando = true;
    try {
      const saida = wrap.animate(
        [{ opacity: 1, transform: 'translateX(0)' }, { opacity: 0, transform: `translateX(${-16 * d}px)` }],
        { duration: 110, easing: 'ease-in', fill: 'forwards' }
      );
      await saida.finished;
      trocar();
      const entrada = wrap.animate(
        [{ opacity: 0, transform: `translateX(${16 * d}px)` }, { opacity: 1, transform: 'translateX(0)' }],
        { duration: 150, easing: 'ease-out' }
      );
      // O fill da saída manteria o conteúdo invisível depois da entrada.
      saida.cancel();
      await entrada.finished;
    } finally {
      navegando = false;
    }
  }

  function perguntaAtual() {
    return perguntas[currentQ - 1];
  }

  function normalizarResposta(raw) {
    if (typeof raw === 'object' && raw !== null) return raw;
    return { valor: raw || '', textoLivre: '' };
  }

  function respostaDaPergunta(q) {
    return normalizarResposta(respostas[q.id]);
  }

  function salvarLocal() {
    sessionStorage.setItem(storageKey, JSON.stringify(respostas));
  }

  function carregarLocal() {
    try {
      respostas = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
    } catch (_) {
      respostas = {};
    }
  }

  function aplicarEstilosExtras() {
    if (document.getElementById('questionarioApiStyles')) return;
    const style = document.createElement('style');
    style.id = 'questionarioApiStyles';
    style.textContent = `
      .text-answer {
        width: 100%;
        min-height: 52px;
        background: rgba(17,24,39,0.8);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px;
        padding: 1rem 1.1rem;
        color: #f0f6ff;
        font-family: 'Manrope', sans-serif;
        font-size: 0.92rem;
        outline: none;
        resize: vertical;
      }
      .text-answer:focus {
        border-color: rgba(37,99,235,0.55);
        background: rgba(37,99,235,0.07);
      }
      .free-label {
        display: block;
        color: rgba(255,255,255,0.45);
        font-family: 'Manrope', sans-serif;
        font-size: 0.78rem;
        line-height: 1.5;
        margin: 0.2rem 0 0.55rem;
      }
      .question-error {
        display: none;
        background: rgba(220,38,38,0.12);
        border: 1px solid rgba(220,38,38,0.28);
        border-radius: 12px;
        color: #fca5a5;
        font-family: 'Manrope', sans-serif;
        font-size: 0.82rem;
        padding: 0.75rem 1rem;
        margin-bottom: 1rem;
        text-align: center;
      }
    `;
    document.head.appendChild(style);
  }

  function mostrarErro(msg) {
    let el = document.getElementById('questionError');
    if (!el) {
      el = document.createElement('div');
      el.id = 'questionError';
      el.className = 'question-error';
      document.getElementById('questionCard')?.prepend(el);
    }
    el.textContent = msg;
    el.style.display = 'block';
  }

  function esconderErro() {
    const el = document.getElementById('questionError');
    if (el) el.style.display = 'none';
  }

  function respostaPreenchida(q) {
    const resposta = respostaDaPergunta(q);
    if (q.tipo === 'texto' || q.tipo === 'numero' || q.tipo === 'texto_livre' || !q.opcoes) {
      return String(resposta.valor || '').trim().length > 0 || q.obrigatorio === false;
    }
    return String(resposta.valor || '').trim().length > 0;
  }

  function renderPergunta(goingBack = false) {
    if (!perguntas.length) return;

    const q = perguntaAtual();
    const card = document.getElementById('questionCard');
    const btnVoltar = document.getElementById('btnVoltar');
    const list = document.getElementById('optionsList');

    esconderErro();
    if (modoBlocos) {
      // A animação fica no trocarTela; a classe não muda entre perguntas.
      card.className = 'question-card';
      card.hidden = false;
      document.getElementById('blockIntro').hidden = true;
      const b = blocoDaPergunta(currentQ);
      document.getElementById('questionNum').textContent = `${b.nome} — ${b.posicao} de ${b.tamanho}`;
      renderProgressoBlocos(b.indice, b.posicao / b.tamanho);
    } else {
      card.className = 'question-card' + (goingBack ? ' going-back' : '');
      document.getElementById('questionNum').textContent = `Pergunta ${String(currentQ).padStart(2, '0')}`;
      document.getElementById('navCurrent').textContent = currentQ;
      document.getElementById('navTotal').textContent = perguntas.length;
      document.getElementById('progressBar').style.width = `${(currentQ / perguntas.length) * 100}%`;
    }
    document.getElementById('questionText').textContent = q.texto;
    btnVoltar.disabled = currentQ === 1;
    list.innerHTML = '';

    const resposta = respostaDaPergunta(q);

    if (q.opcoes && q.opcoes.length) {
      q.opcoes.forEach((op) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'option-btn font-manrope' + (resposta.valor === op.letra ? ' selected' : '');
        btn.innerHTML = `<div class="option-letter font-jakarta">${op.letra}</div><span>${op.texto}</span>`;
        btn.onclick = () => selecionarResposta(q, op.letra);
        list.appendChild(btn);
      });

      if (q.textoLivre) {
        const label = document.createElement('label');
        label.className = 'free-label';
        label.textContent = q.textoLivre;
        const textarea = document.createElement('textarea');
        textarea.className = 'text-answer';
        textarea.rows = 3;
        textarea.placeholder = 'Opcional';
        textarea.value = resposta.textoLivre || '';
        textarea.addEventListener('input', () => {
          respostas[q.id] = { ...respostaDaPergunta(q), textoLivre: textarea.value };
          salvarLocal();
        });
        list.appendChild(label);
        list.appendChild(textarea);
      }
    } else {
      const input = document.createElement(q.tipo === 'texto_livre' ? 'textarea' : 'input');
      input.className = 'text-answer';
      input.placeholder = q.placeholder || 'Digite sua resposta';
      if (q.tipo === 'numero') input.type = 'number';
      if (q.tipo === 'texto_livre') input.rows = 5;
      input.value = resposta.valor || '';
      input.addEventListener('input', () => {
        respostas[q.id] = { valor: input.value, textoLivre: '' };
        salvarLocal();
        atualizarBtnProximo();
      });
      list.appendChild(input);
      setTimeout(() => input.focus(), 50);
    }

    atualizarBtnProximo();
    history.replaceState(null, '', `?q=${currentQ}`);
  }

  async function selecionarResposta(q, valor) {
    respostas[q.id] = { ...respostaDaPergunta(q), valor };
    salvarLocal();
    renderPergunta();
    // Salva no servidor em background — não trava a UI
    salvarResposta(q).catch(() => {});
  }

  async function salvarResposta(q) {
    const resposta = respostaDaPergunta(q);
    if (isTesteInicial) {
      return testeApi.salvarResposta(q.id, resposta.valor, resposta.textoLivre || '');
    }
    return modulosApi.salvarResposta(moduloId, q.id, resposta.valor, resposta.textoLivre || '');
  }

  async function salvarTodas() {
    for (const q of perguntas) {
      if (respostaPreenchida(q)) await salvarResposta(q);
    }
  }

  function atualizarBtnProximo() {
    const q = perguntaAtual();
    const btn = document.getElementById('btnProximo');
    const isLast = currentQ === perguntas.length;
    const enabled = q && respostaPreenchida(q);

    btn.className = 'btn-proximo font-jakarta' + (enabled ? ' enabled' : '');
    btn.innerHTML = isLast
      ? `Finalizar <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>`
      : `Próxima <svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path d="M5 12h14M12 5l7 7-7 7"/></svg>`;
    btn.onclick = isLast ? finalizar : proximaPergunta;
  }

  function proximaPergunta() {
    if (navegando) return;
    const q = perguntaAtual();
    if (!respostaPreenchida(q)) return;
    if (currentQ >= perguntas.length) {
      finalizar();
      return;
    }
    if (modoBlocos) {
      const atual = blocoDaPergunta(currentQ);
      const proximo = blocoDaPergunta(currentQ + 1);
      if (proximo.indice !== atual.indice) {
        // currentQ continua na última pergunta do bloco até o aluno continuar.
        trocarTela(() => mostrarIntroBloco(proximo.indice), 'frente');
        return;
      }
      currentQ++;
      trocarTela(() => renderPergunta(), 'frente');
      return;
    }
    currentQ++;
    renderPergunta(false);
  }

  function continuarBloco() {
    if (navegando) return;
    currentQ++;
    trocarTela(() => renderPergunta(), 'frente');
  }

  function voltarDaIntro() {
    if (navegando) return;
    trocarTela(() => renderPergunta(), 'tras');
  }

  function voltarPergunta() {
    if (navegando) return;
    if (currentQ <= 1) return;
    currentQ--;
    if (modoBlocos) {
      trocarTela(() => renderPergunta(), 'tras');
      return;
    }
    renderPergunta(true);
  }

  async function finalizar() {
    if (enviando) return;
    const faltando = perguntas.find((q) => !respostaPreenchida(q));
    if (faltando) {
      currentQ = perguntas.indexOf(faltando) + 1;
      renderPergunta();
      mostrarErro('Responda esta pergunta para continuar.');
      return;
    }

    enviando = true;
    const btn = document.getElementById('btnProximo');
    btn.textContent = 'Enviando...';
    btn.disabled = true;

    try {
      // Salva todas em paralelo — muito mais rápido que sequencial
      await Promise.allSettled(
        perguntas.filter(q => respostaPreenchida(q)).map(q => salvarResposta(q))
      );

      if (isTesteInicial) {
        const payload = perguntas.map((q) => ({
          perguntaId: String(q.id),
          valor: respostaDaPergunta(q).valor,
          textoLivre: respostaDaPergunta(q).textoLivre || ''
        }));
        const data = await testeApi.finalizar(payload);
        sessionStorage.setItem('pf_job_id', data.jobId);
        sessionStorage.removeItem(storageKey);
        window.location.href = 'resultado.html';
        return;
      }

      const data = await modulosApi.finalizar(moduloId);
      sessionStorage.removeItem(storageKey);
      if (data.jobId) sessionStorage.setItem('pf_job_id', data.jobId);
      window.location.href = data.jobId ? 'resultado.html' : 'historico.html';
    } catch (error) {
      mostrarErro(error?.detail?.erro || error?.erro || error?.detail || 'Não foi possível enviar suas respostas.');
      btn.disabled = false;
      enviando = false;
      atualizarBtnProximo();
    }
  }

  function sair() {
    salvarLocal();
    window.location.href = isTesteInicial ? 'inicial_logada.html' : 'historico.html';
  }

  async function carregarPerguntas() {
    aplicarEstilosExtras();
    carregarLocal();

    const protegido = await protegerPagina({
      precisaMapaFeito: isTesteInicial ? false : null
    });
    if (!protegido) return;

    try {
      const data = isTesteInicial
        ? await testeApi.perguntas()
        : await modulosApi.perguntas(moduloId);
      perguntas = data.perguntas || [];
      montarBlocos();
      if (modoBlocos) {
        document.getElementById('blockIntroContinuar').onclick = continuarBloco;
        document.getElementById('blockIntroVoltar').onclick = voltarDaIntro;
      }
      currentQ = qParam && qParam >= 1 && qParam <= perguntas.length ? qParam : 1;
      renderPergunta();
    } catch (error) {
      if (!isTesteInicial && error?.status === 403) {
        mostrarErro(error?.detail?.erro || 'Responda todas as perguntas iniciais para liberar os módulos.');
        setTimeout(() => {
          window.location.href = 'inicial_logada.html';
        }, 1800);
        return;
      }
      mostrarErro(error?.detail?.erro || error?.erro || error?.detail || 'Não foi possível carregar as perguntas.');
    }
  }

  window.proximaPergunta = proximaPergunta;
  window.voltarPergunta = voltarPergunta;
  window.finalizarTeste = finalizar;
  window.finalizarModulo = finalizar;
  window.sair = sair;

  carregarPerguntas();
})();