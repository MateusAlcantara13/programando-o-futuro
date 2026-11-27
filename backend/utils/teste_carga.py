import asyncio, httpx, os

# Endereço do backend a testar. Padrão: o backend local. Para outro
# endereço, defina PF_URL_CARGA antes de rodar. Nenhum endereço de
# produção fica escrito aqui.
URL = os.getenv("PF_URL_CARGA", "http://127.0.0.1:8000").rstrip("/")

# Simula um usuário completo: cadastra, responde tudo e finaliza (chama a IA)
async def simular_usuario(i):
    async with httpx.AsyncClient(timeout=180) as client:

        # 1. Cadastra
        r = await client.post(f"{URL}/api/auth/cadastro", json={
            "nome": f"Teste Carga {i}",
            "email": f"carga{i}_{int(asyncio.get_event_loop().time())}@teste.com",
            "senha": "123456",
            # Usuário de teste de carga: aceita a versão atual do termo,
            # que o cadastro exige desde 26/11/2026.
            "aceite_lgpd": True,
            "versao_termo_lgpd": VERSAO_TERMO,
        })
        if r.status_code != 201:
            print(f"❌ Usuário {i} — erro no cadastro: {r.status_code} {r.text[:100]}")
            return

        token = r.json().get("token")
        headers = {"Authorization": f"Bearer {token}"}
        print(f"👤 Usuário {i} cadastrado")

        # 2. Salva respostas uma por uma (como o site faz)
        for pid in range(1, 23):
            await client.patch(f"{URL}/api/testeinicial/resposta",
                headers=headers,
                json={"perguntaId": str(pid), "valor": "A", "textoLivre": ""}
            )

        print(f"📝 Usuário {i} respondeu todas as perguntas")

        # 3. Finaliza — aqui é onde chama a IA
        r2 = await client.post(f"{URL}/api/testeinicial/finalizar",
            headers=headers,
            json={"respostas": []}
        )
        if r2.status_code != 200:
            print(f"❌ Usuário {i} — erro ao finalizar: {r2.status_code} {r2.text[:200]}")
            return

        job_id = r2.json().get("jobId")
        print(f"🤖 Usuário {i} — IA processando (job: {job_id[:8]}...)")

        # 4. Aguarda o resultado da IA
        for tentativa in range(30):  # aguarda até 60s
            await asyncio.sleep(2)
            r3 = await client.get(f"{URL}/api/resultado/status?jobId={job_id}", headers=headers)
            status = r3.json().get("status")
            if status == "concluido":
                print(f"✅ Usuário {i} — CONCLUÍDO com sucesso!")
                return
            elif status == "erro":
                erro = r3.json().get("erro", "?")
                print(f"❌ Usuário {i} — ERRO na IA: {erro}")
                return

        print(f"⏱️ Usuário {i} — timeout aguardando resultado da IA")

VERSAO_TERMO = None

async def main():
    global VERSAO_TERMO
    async with httpx.AsyncClient(timeout=30) as client:
        VERSAO_TERMO = (await client.get(f"{URL}/api/lgpd/termo")).json()["versao"]
    N = 15 # quantidade de usuários simultâneos — pode aumentar para testar mais
    print(f"🚀 Simulando {N} usuários respondendo e chamando a IA ao mesmo tempo...\n")
    await asyncio.gather(*[simular_usuario(i) for i in range(N)])
    print(f"\n✅ Teste concluído! Confira o painel admin para ver os resultados.")

asyncio.run(main())