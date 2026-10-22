# Gerenciador de Usuários do CasaOS

[English](README.md) | **Português (Brasil)**

Uma página web para adicionar, remover e trocar a senha dos usuários do
[CasaOS](https://casaos.io), com login próprio. Útil quando você esqueceu a
senha do CasaOS.

> [!NOTE]
> **Este é um fork apenas do [BigBearCasaOS User Management](https://github.com/bigbeartechworld/big-bear-docker-images/tree/main/Apps/big-bear-casaos-user-management).**
> Esse app é uma única pasta (`Apps/big-bear-casaos-user-management`) do
> repositório [big-bear-docker-images](https://github.com/bigbeartechworld/big-bear-docker-images), que tem muitas outras imagens,
> então não dá para fazer fork só dele no GitHub. Este repositório partiu
> apenas daquela pasta (versão 0.1.1) e de nada mais do big-bear-docker-images.
> O original por sua vez é baseado no [casaos-user-management](https://github.com/carlbomsdata/casaos-user-management).
> Sem afiliação com a BigBearTechWorld.

## O que mudou em relação à versão da BigBear

- **O login funciona quando você troca.** O antigo comparava o pop-up de Basic
  Auth do navegador com `ADMIN_USERNAME`/`ADMIN_PASSWORD` caractere por
  caractere, sem nenhuma pista quando eram diferentes. Agora:
  - há uma página de login de verdade (cookie de sessão, botão de sair);
  - espaços e aspas em volta das variáveis são removidos;
  - o login pode ser trocado **na própria página** (botão da chave), e
    continua valendo depois de reiniciar ou atualizar;
  - o log diz qual login está valendo e o tamanho dele
    (`Admin login: user 'casaos' (6 characters), password of 11 characters`),
    então um valor estragado fica fácil de ver;
  - `RESET_ADMIN=true` volta para o login das variáveis se você ficar trancado
    para fora.
- **Toda ação exige o login.** Antes só a lista de usuários era protegida:
  adicionar, remover e trocar a senha de usuários do CasaOS funcionava sem
  login. Os formulários também têm proteção contra CSRF, e 5 logins errados
  bloqueiam o endereço por 5 minutos.
- As mensagens de sucesso e erro aparecem (nunca apareciam).
- Não dá para remover o último usuário do CasaOS; uma cópia do `user.db` fica
  em `user.db.bak` antes de cada alteração.
- Sem servidor de debug em produção (gunicorn), chave de sessão aleatória,
  healthcheck, container sem `privileged`, sem o pacote systemd na imagem (o
  serviço de usuários é acessado por D-Bus).
- A interface funciona sem internet (CSS e ícones estão dentro da imagem) e
  segue o idioma do navegador (inglês, português).

## Instalar no CasaOS

1. Desinstale a versão da BigBear se tiver (as duas usam a porta 5000).
2. **App Store → Mais apps**, adicione
   `https://usuariodejava.github.io/CasaOS-User-Management/store.zip` (ela
   aparece como **CasaOS-User-Management**) e instale o **Gerenciador de
   Usuários do CasaOS**.

   Ou **App Store → Instalação personalizada → Importar**, e cole o
   [`Apps/casaos-user-management/docker-compose.yml`](Apps/casaos-user-management/docker-compose.yml).
3. Abra o app (porta 5000) e entre com **casaos / casaos**.
4. Troque esse login logo de cara: botão da chave no topo.

## O login desta página

Não é uma conta do CasaOS. Ele vem de, nesta ordem:

1. O login definido na página (botão da chave), guardado em
   `/DATA/AppData/casaos-user-management/admin.json` (senha com hash).
2. As variáveis `ADMIN_USERNAME` e `ADMIN_PASSWORD` (no CasaOS: configurações
   do app).
3. `casaos` / `casaos`.

A alteração mais recente vale: se você editar as variáveis no CasaOS depois de
trocar o login na página, as variáveis passam a valer.

O usuário não diferencia maiúsculas de minúsculas; a senha diferencia.

**Login recusado?** O log do app (CasaOS: configurações do app → *Logs*, ou
`docker logs casaos-user-management`) diz qual login está valendo ao iniciar e
por que cada tentativa falhou, por exemplo `user 'casaos' is not the configured
user 'UsuarioDeJava' (from ADMIN_USERNAME)` ou `wrong password: 9 characters
typed, the configured one has 10`. Senhas nunca aparecem no log.

**Ficou trancado para fora?** Coloque `RESET_ADMIN` como `true` nas
configurações do app, salve (o app reinicia com o login das variáveis), entre,
e volte para `false`.

Um `$` numa variável precisa ser escrito `$$` num arquivo docker-compose, senão
o Docker o substitui. Trocar o login na página não tem essa limitação.

## Variáveis

| Variável | Padrão | |
| --- | --- | --- |
| `ADMIN_USERNAME` | `casaos` | Usuário desta página |
| `ADMIN_PASSWORD` | `casaos` | Senha desta página |
| `RESET_ADMIN` | `false` | `true` esquece o login definido na página |
| `SECRET_KEY` | aleatória, guardada em `/data/secret_key` | Chave do cookie de sessão |
| `CASAOS_DB` | `/var/lib/casaos/db/user.db` | Banco de usuários do CasaOS |
| `LOG_LEVEL` | `INFO` | |

## Volumes

| Container | Host | |
| --- | --- | --- |
| `/var/lib/casaos/db` | `/var/lib/casaos/db` | Banco de usuários do CasaOS |
| `/data` | `/DATA/AppData/casaos-user-management` | Login desta página |
| `/var/run/dbus/system_bus_socket` | o mesmo | Opcional: mostra o estado do serviço de usuários do CasaOS e o reinicia depois do *Resetar banco de dados* |

O `apparmor:unconfined` só é necessário para a parte do D-Bus (o perfil
AppArmor padrão do Docker bloqueia). Sem o socket, todo o resto funciona, e
depois do *Resetar banco de dados* você mesmo reinicia o CasaOS
(`sudo systemctl restart casaos-user-service`).

## Como ele altera os usuários do CasaOS

O CasaOS (CasaOS-UserService) guarda os usuários na tabela SQLite `o_users` e
confere um login comparando `md5(senha)` com a coluna `password`, lendo a
tabela a cada login. Então uma alteração feita aqui vale já no próximo login do
CasaOS, sem reiniciar nada. *Resetar banco de dados* apaga o `user.db` e
reinicia o serviço de usuários, que cria um vazio; o CasaOS então mostra a
tela de primeiro acesso.

## Desenvolvimento

```bash
pip install -r requirements.txt pytest
pytest                      # testes contra um user.db falso do CasaOS
docker build -t casaos-user-management .
```

Rodar localmente (CSS e ícones são gerados pelo Dockerfile, então use a
imagem):

```bash
docker run --rm -p 5000:5000 \
  -v /var/lib/casaos/db:/var/lib/casaos/db \
  -v "$PWD/data:/data" casaos-user-management
```

O CI (`.github/workflows/ci.yml`) roda os testes, publica
`ghcr.io/usuariodejava/casaos-user-management` (amd64, arm/v7, arm64) a partir
da `main`, e publica `Apps/` como `store.zip` no GitHub Pages.

## Licença

MIT, veja [LICENSE](LICENSE).
