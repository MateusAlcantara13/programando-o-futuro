// ============================================================
// js/mapa-progresso.js — Progresso do mapa de carreira
// Programando o Futuro
// ============================================================
//
// O SERVIDOR é a fonte da verdade do progresso. O navegador guarda só um
// cache (pf_mapa_done, pf_mapa_checks) para a tela aparecer rápido.
//
// - Carga: mostra o cache, busca o servidor e, se ele responder, sobrescreve
//   o cache e a tela. Se o servidor não responder, avisa que o que aparece
//   pode estar desatualizado.
// - Salvar: grava o cache e envia ao servidor. Se o envio falhar, avisa que
//   a marcação NÃO foi salva. Nunca falha em silêncio: o aluno via o visto
//   na tela e perdia tudo ao fechar o navegador, sem saber.
// - Os envios saem em fila, um de cada vez. Cada envio leva o estado
//   inteiro, então um envio antigo chegando depois de um novo apagaria a
//   marcação mais recente no servidor.
//
// Sem dependência de página: quem usa passa o armazenamento, as funções de
// rede e o que fazer com os avisos. É isso que permite testar o ciclo
// inteiro fora do navegador (backend/testes/teste_mapa_progresso*.py).

const CHAVES_PROGRESSO_MAPA = { etapas: 'pf_mapa_done', checks: 'pf_mapa_checks' };

function criarProgressoMapa({ armazenamento, buscar, enviar, aoAvisar }) {
  // Os objetos são sempre os mesmos e só têm o conteúdo trocado, para quem
  // guardou uma referência a eles (a página) continuar vendo o estado atual.
  const estado = { etapasConcluidas: {}, checksFeitos: {} };
  let fila = Promise.resolve();

  function substituir(alvo, novo) {
    Object.keys(alvo).forEach((k) => { delete alvo[k]; });
    Object.assign(alvo, novo || {});
  }

  function lerJson(chave) {
    try { return JSON.parse(armazenamento.getItem(chave) || '{}') || {}; } catch (e) { return {}; }
  }

  function gravarCache() {
    armazenamento.setItem(CHAVES_PROGRESSO_MAPA.etapas, JSON.stringify(estado.etapasConcluidas));
    armazenamento.setItem(CHAVES_PROGRESSO_MAPA.checks, JSON.stringify(estado.checksFeitos));
  }

  // aoAtualizar é chamado depois de aplicar o cache e de novo depois de
  // aplicar o servidor. Devolve 'servidor' ou 'cache' (servidor não respondeu).
  async function carregar(aoAtualizar) {
    substituir(estado.etapasConcluidas, lerJson(CHAVES_PROGRESSO_MAPA.etapas));
    substituir(estado.checksFeitos, lerJson(CHAVES_PROGRESSO_MAPA.checks));
    if (aoAtualizar) aoAtualizar();
    try {
      const dados = await buscar();
      if (!dados) throw new Error('sem resposta do servidor');
      substituir(estado.etapasConcluidas, dados.etapasConcluidas);
      substituir(estado.checksFeitos, dados.checksFeitos);
      gravarCache();
      aoAvisar(null);
      if (aoAtualizar) aoAtualizar();
      return 'servidor';
    } catch (e) {
      aoAvisar('carga');
      return 'cache';
    }
  }

  // Devolve uma promessa que resolve true se o servidor gravou, false se não.
  function salvar() {
    gravarCache();
    const envio = fila.then(async () => {
      try {
        // Estado lido na hora do envio: sai sempre o mais recente.
        await enviar({ etapasConcluidas: estado.etapasConcluidas, checksFeitos: estado.checksFeitos });
        aoAvisar(null);
        return true;
      } catch (e) {
        aoAvisar('salvar');
        return false;
      }
    });
    fila = envio;
    return envio;
  }

  return { estado, carregar, salvar };
}
