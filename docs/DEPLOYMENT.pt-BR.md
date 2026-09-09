# Implantação Docker — 2026.09.08.4

Esta versão atualiza o contêiner `binternet` existente na VPS IONOS. O contêiner separado `binternet-candidate-20260907` permanece intacto.

## Copiar e atualizar a partir do seu computador

Baixe `binternet-securityops-2026.09.08.4.tar.gz` para `~/Downloads`. O arquivo contém a pasta `binternet-securityops-2026.09.08.4`. Execute no fish, bash ou zsh:

```sh
scp -P 5119 ~/Downloads/binternet-securityops-2026.09.08.4.tar.gz root@securityops.co:/root/ && ssh -p 5119 root@securityops.co 'bash -c "set -e; install -d -m 700 /opt/binternet-releases; tar -xzf /root/binternet-securityops-2026.09.08.4.tar.gz -C /opt/binternet-releases; cd /opt/binternet-releases/binternet-securityops-2026.09.08.4; sha256sum --quiet -c MANIFEST.sha256; bash deploy/upgrade.sh"'
```

A VPS precisa de Docker e Python 3, além de acesso ao registro de imagens, repositórios Alpine, Pinterest e CDN de imagens. A autenticação SSH existente é utilizada; o projeto não contém credenciais. Repetir a extração desta mesma versão sobrescreve a pasta do código; mantenha alterações locais separadas.

## Fluxo da atualização

1. Inspeciona o contêiner ativo e salva uma cópia privada em `/opt/binternet-backups/<data-id>/`: pasta com permissão 0700 e arquivo com 0600. A cópia pode conter variáveis secretas; não a compartilhe.
2. Recusa volumes/montagens personalizados, IP estático do contêiner, rede host/compartilhada, modo privilegiado, dispositivos, capacidades adicionais e portas não suportadas antes de parar a produção. Essas configurações precisam de uma migração explícita.
3. Compila a imagem com a produção em execução. O ID da imagem testada é utilizado tanto no candidato quanto no novo contêiner definitivo.
4. Cria um candidato de nome exclusivo em uma porta aleatória de `127.0.0.1`, sem ocupar 5134 nem 15134. Verifica saúde Docker, JSON de saúde com a versão exata, formulário de busca, CSS das galerias e o script local de rolagem infinita. Busca `architecture` no Pinterest, exige imagens e um link Next page válido na primeira página, segue esse link e exige novas imagens distintas na segunda página. As duas páginas reais precisam passar antes da troca.
5. Remove somente esse candidato, para a produção e mantém o original com nome `binternet-rollback-<data-id>`. Inicia a nova versão com o nome `binternet` e confirma sua saúde. A política de reinício do original retido é temporariamente desativada para impedir conflitos de porta após reiniciar a VPS; a reversão restaura a política e o número de tentativas originais. Existe uma breve interrupção durante essa troca; não é uma implantação sem indisponibilidade.
6. Preserva as portas publicadas — inclusive `0.0.0.0:5134` —, variáveis de ambiente, política de reinício, limites de recursos existentes, DNS, hosts adicionais, rótulos da aplicação, redes Docker e aliases. Os rótulos de propriedade do Compose não são transferidos, pois o novo contêiner é gerenciado pelo script. Executar um Compose antigo depois pode substituir a atualização.
7. Se a troca falhar, tenta restaurar automaticamente o original, incluindo nome e aliases. Ao terminar, mostra o comando exato para reversão manual.

Variáveis de ambiente com múltiplas linhas são recusadas. O diretório de cache deve estar dentro de `/tmp`. Se não houver limite de memória anterior, é aplicado um teto de 1536 MiB; um limite existente é preservado. Reserve memória e espaço para a produção e o candidato temporário simultaneamente.

Se o Pinterest estiver indisponível, a verificação padrão impede a troca. Para aceitar explicitamente que a disponibilidade da busca não foi confirmada, execute na VPS:

```sh
bash /opt/binternet-releases/binternet-securityops-2026.09.08.4/deploy/upgrade.sh --skip-upstream-check
```

Essa opção ignora as duas verificações de páginas reais do Pinterest. As verificações locais de saúde, página inicial, CSS e script continuam ativas. Ela não corrige bloqueios, indisponibilidade ou falhas de paginação do Pinterest.

## Nginx Proxy Manager

As redes existentes e o nome `binternet` são preservados. O script não reinicia nem reconfigura `npm-attachment`. Um Proxy Host configurado como `http://binternet:8080`, em uma rede compartilhada, pode manter essa configuração. Se utiliza o endereço da VPS e a porta 5134, a publicação anterior também é mantida.

Se a saúde local estiver normal, mas o endereço público retornar 502, o NPM pode ter mantido o IP anterior em cache. Salve somente o Proxy Host afetado na interface do NPM para atualizar sua configuração; não é necessário reiniciar todo o proxy.

Após atualizar, abra o endereço público configurado no NPM e verifique o serviço local:

```sh
ssh -p 5119 root@securityops.co 'docker ps --filter name=binternet; curl --fail --silent --show-error http://127.0.0.1:5134/health.php'
```

O endpoint de saúde verifica dependências e cache, sem acessar o Pinterest. A busca real e sua continuação são validadas separadamente nas duas páginas verificadas durante o teste do candidato. A disponibilidade futura do serviço externo não pode ser garantida.

## Reversão

Mantenha o contêiner original parado até confirmar que a nova versão está funcionando. Não execute limpeza de contêineres parados nesse período. Use na VPS o comando exato exibido pelo script:

```sh
python3 /opt/binternet-backups/DATA-ID/upgrade.py rollback /opt/binternet-backups/DATA-ID/deployment.json
```

Troque `DATA-ID` pelo diretório da implantação real. O programa de reversão fica junto da cópia privada e continua disponível caso a pasta extraída do projeto seja removida. Antes de excluir a nova versão, ele confirma a existência do original e verifica se o contêiner atual pertence àquela implantação.

Falhas comuns, Ctrl+C, SIGTERM e encerramento da conexão SSH após o início da troca acionam a restauração automática. Queda de energia, falha do Docker e SIGKILL podem interrompê-la; utilize o comando salvo quando a VPS estiver disponível. Um bloqueio impede atualizações e reversões simultâneas.

## Instalação nova

O `docker-compose.yml` serve para uma instalação sem outro contêiner chamado `binternet`:

```sh
docker compose up -d --build
```

Ele publica `127.0.0.1:5134`. Para NPM em Docker, conecte o serviço à rede real compartilhada com o NPM e utilize `http://binternet:8080`. Na VPS atual, prefira o script de atualização para preservar a configuração existente.

## Proteções e testes

A imagem utiliza Alpine 3.24 e PHP 8.4. Nginx e PHP-FPM rodam sem privilégios, com supervisão de processos e `tini`. O sistema de arquivos raiz é somente leitura; capacidades Linux são removidas e elevação de privilégios é bloqueada. Os diretórios temporários possuem tmpfs limitado. O cache é descartável e não é migrado.

Somente cinco endpoints PHP públicos, arquivos CSS/imagens, o script exato `/static/infinite-scroll.js` e o download exato `/source.tar.gz` podem ser servidos. Esse arquivo é criado durante a compilação Docker e contém o código correspondente à versão implantada, licença, arquivos de compilação/implantação, testes e documentação. Metadados Git, segredos de ambiente, caches e artefatos gerados são excluídos. Revise o contexto de compilação antes de adicionar arquivos privados a um fork, pois o download publica intencionalmente o código incluído. Código interno, testes, scripts, documentação e metadados do repositório não ficam acessíveis pela web. A CSP permite scripts e requisições fetch apenas da mesma origem (`script-src 'self'; connect-src 'self'`) e bloqueia scripts e estilos inline. O script local só é carregado quando a rolagem infinita é selecionada e existe outra página de resultados; a paginação manual funciona sem JavaScript. Os logs Nginx omitem parâmetros das URLs. Há limites de requisições para busca e imagens, sem limitar o endpoint de saúde. Atrás do NPM, esses limites são agregados pelo endereço do proxy; cabeçalhos arbitrários de cliente não são confiados.

Execute os testes da atualização com:

```sh
python3 -m unittest discover -s deploy -p 'test_*.py' -v
```

Eles simulam a interface Docker para verificar preservação de configurações, permissões privadas, falha do candidato, falha durante a troca, restauração, uso do ID da imagem testada e proteção de outros contêineres. Esses testes não equivalem a compilar e executar a imagem real. O operador confirmou o funcionamento da versão .3 na VPS. O ambiente de desenvolvimento não possui Docker nem permite verificar o Pinterest ao vivo ou utilizar um navegador real para estes testes. A compilação da imagem .4, as duas páginas reais e a verificação no navegador continuam pendentes em um ambiente com esse acesso. Nenhum acesso SSH ou implantação da .4 foi realizado durante a preparação desta versão.

## Diagnóstico de falhas na inicialização

A correção introduzida na versão 2026.09.08.2 resolve a falha observada ao criar `/var/lib/nginx/tmp/proxy` no sistema de arquivos somente para leitura. Os cinco diretórios temporários do Nginx usam agora o tmpfs já existente, e `-e stderr` evita o caminho padrão do log durante a inicialização. As proteções continuam ativas.

Se o candidato falhar, o atualizador mostra a pasta privada `failure-diagnostics` dentro do backup da implantação. Ela preserva logs, estado/saúde, inspeção e erros do Docker antes de remover o candidato. Esses arquivos podem conter configuração sensível; compartilhe apenas as linhas relevantes ao erro.


## Compatibilidade com o Pinterest na .3

O candidato .2 ficou saudável, mas o Pinterest respondeu HTTP 403. A versão .3 inclui o cabeçalho de roteamento usado pelos clientes mantidos. O comando normal acima continua exigindo imagens reais antes da troca. Se houver nova recusa, o erro identifica `/search.php` e `Pinterest HTTP 403`, com os dados estruturados no arquivo privado `failure-diagnostics/failure.json`. Veja [a evidência da correção](PINTEREST_403_FIX.md).


## Paginação e rolagem infinita opcional na .4

O parser agora lê `resource.options.bookmarks[0]`; marcadores explícitos de fim têm prioridade sobre os metadados antigos. As chaves de cache da busca passam a usar o prefixo `v2:`, impedindo que um resultado armazenado pela .3 sem continuação esconda o link corrigido. A paginação manual permanece como padrão. Selecionar Infinite scroll inclui `scroll=infinite` nos links de busca e paginação.

O navegador carrega uma página da mesma origem por vez, com prazo de 15 segundos e limite de 2 MiB para a resposta HTML. Os cartões são reconstruídos a partir de dados validados; imagens duplicadas são descartadas. Páginas repetidas e erros interrompem novas requisições automáticas. Os controles Pause, Retry loading e Next page ficam disponíveis conforme o estado. Não existe um teto fixo de páginas, mas os cartões já carregados continuam consumindo memória do navegador. Veja [a correção e os limites de verificação](PAGINATION_FIX.md).
