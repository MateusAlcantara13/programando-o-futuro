# 🎯 Programando o Futuro

Plataforma web que usa a **API do Claude (Anthropic)** para ajudar estudantes da rede pública a descobrirem caminhos de carreira de forma personalizada. A partir de um questionário, o sistema gera um **mapa visual de carreira** com áreas recomendadas, cursos, instituições de ensino e os próximos passos concretos para chegar lá.

O projeto nasceu de um problema simples: jovens de escola pública terminam o ensino médio sem informação concreta sobre o próximo passo. Os testes vocacionais existentes param no resultado, dizem a área e não explicam como entrar, quais instituições são viáveis, nem como está o mercado daquela profissão.

Desenvolvido em equipe no programa de extensão universitária **Conectados pela Comunidade**, do Centro Universitário SENAI-SP.

## ✨ Funcionalidades

- Questionário de 22 perguntas que mapeia interesses, contexto e perfil do estudante
- Geração de recomendações personalizadas via API do Claude
- Mapa visual de carreira com trilhas, cursos e instituições recomendadas
- Módulos de aprofundamento por área
- Página de oportunidades com vagas e caminhos de ingresso
- Autenticação com JWT e aceite de LGPD no cadastro
- Backend com API própria para processar respostas e armazenar progresso

## 🛠️ Tecnologias

**Backend**
- Python + FastAPI
- MySQL (Aiven)
- PyJWT para autenticação
- httpx para as chamadas à API do Claude

**Frontend**
- HTML5, CSS3 e JavaScript puro
- jsPDF para exportar o mapa de carreira

**Infraestrutura**
- Deploy na Render
- Variáveis de ambiente para chaves e credenciais

## 📁 Estrutura

```
programando-o-futuro/
├── backend/
│   ├── main.py             # API (FastAPI): auth, questionário, geração do mapa
│   ├── requirements.txt
│   ├── .env.example        # Modelo das variáveis de ambiente
│   ├── ca.pem              # Certificado público da Aiven (conexão TLS com o banco)
│   └── utils/
│       └── teste_carga.py  # Script de teste de carga simulando uma turma inteira
├── js/
│   ├── api.js              # Comunicação com o backend
│   ├── questionario-api.js # Lógica do questionário
│   ├── sidebar.js
│   └── footer.js
├── pages/                  # Páginas do frontend
├── partials/               # Componentes de HTML reutilizáveis
├── styles/
├── assets/
└── index.html
```

## 🚀 Como rodar localmente

### Backend

```bash
cd backend
cp .env.example .env      # preencha com suas credenciais
pip install -r requirements.txt
uvicorn main:app --reload
```

### Frontend

Abra o `index.html` no navegador ou sirva a pasta raiz com um servidor local (a extensão Live Server do VS Code resolve).

> O backend não sobe sem as variáveis de ambiente configuradas. Nunca versione o arquivo `.env`, o `.gitignore` já o protege.

## 🧪 Validação em campo

A plataforma foi aplicada presencialmente em uma escola estadual, em maio de 2026, com **31 alunos** do ensino médio.

A sessão gerou **655 respostas coletadas** com **71,4% de taxa de sucesso** nas submissões. As falhas se concentraram em timeout das chamadas à IA e no envio sequencial das respostas, com 31 usuários submetendo ao mesmo tempo na rede da escola.

As correções feitas depois disso:

- **Retry** nas chamadas à API do Claude, com até 3 tentativas
- **Envio paralelo** das respostas com `Promise.allSettled`, para que uma falha isolada não derrubasse a submissão inteira
- **Script de teste de carga** (`backend/utils/teste_carga.py`), que simula uma turma completa cadastrando, respondendo e gerando o mapa em paralelo

## 👤 Minha contribuição (Mateus Alcantara)

Atuei de ponta a ponta: modelagem do banco, backend em FastAPI, construção e ajuste dos prompts enviados à API do Claude, frontend, deploy na Render e a condução da aplicação presencial na escola, incluindo o diagnóstico das falhas e as correções listadas acima.

## 👥 Equipe

- [Victor Cavalcante](https://github.com/vic-cavalcant3)
- [Mateus Alcantara](https://github.com/MateusAlcantara13)
- Yago Dias dos Santos
- [Ricardo Ongari Rodrigues](https://github.com/RicardoOngari)
- [Lucas Gomes](https://github.com/lucasgsilva102-oss)

Orientação: professor Caio Silva.

> Repositório original do grupo: https://github.com/vic-cavalcant3/Programando-o-Futuro
> Esta cópia foi criada para dar continuidade ao projeto e implementar novas funcionalidades.

## 🔭 Próximos passos

- Observabilidade: log estruturado das gerações e métricas de latência e falha
- Avaliação automatizada com um conjunto fixo de casos de teste, no lugar da revisão manual
- Rate limiting e guardrails nas chamadas à IA
- Ampliação da base de instituições e formas de ingresso

## 📄 Licença

Projeto acadêmico, desenvolvido para fins educacionais.
