# Panela Aberta

Panela Aberta é a aplicação web da Unidade 4 de Processamento de Linguagem Natural, desenvolvida por Pedro Pacheco na FURB. A pessoa informa o que tem em casa e recebe uma recomendação principal, até duas alternativas, os ingredientes disponíveis e ausentes e o link da receita original.

## Executar e validar no computador

No Windows, dê dois cliques em [abrir_panela_aberta.bat](abrir_panela_aberta.bat). Se o site já estiver rodando, o atalho abre a página no navegador. Para iniciar o servidor, ele usa Node.js 22 ou superior, instala as dependências se necessário e abre a página quando estiver pronta. Mantenha a janela do servidor aberta durante o uso e pressione Ctrl+C para pará-lo.

Para executar pelo terminal, comece pela raiz do repositório:

```powershell
cd chatbot-web
npm ci
npm test
npm run dev -- --port 8788
```

Abra [a prévia local](http://127.0.0.1:8788). Faça a sequência abaixo em uma conversa nova.

1. Envie **Tenho banana, aveia, cacau e ovos.** A primeira opção por regras é **Panqueca de banana fit**, com 100% dos ingredientes principais. Confira a fonte e a estimativa de **298,7 kcal, 16,2 g de proteínas, 37,7 g de carboidratos e 11,3 g de gorduras** por porção.
2. Envie **Também tenho cebola. Sem leite e com até 10 minutos.** A conversa continua usando os ingredientes anteriores e as opções respeitam o limite de tempo. Receitas sem dados suficientes mostram “Estimativa nutricional indisponível”.
3. Clique em **Nova conversa** e envie **Tenho leite de coco, mas não tenho leite.** O leite de coco conta como item disponível e o leite comum não.
4. Comece outra conversa e envie **Tenho glitter e parafuso.** O chat pede ingredientes em vez de exibir uma receita sem correspondência. Repita os passos no celular ou na visualização móvel do navegador.

No segundo terminal, dentro de `chatbot-web`, rode a verificação HTTP enquanto o servidor estiver aberto:

```powershell
npm run verify -- http://127.0.0.1:8788
```

## Publicar e validar o Qwen no Cloudflare

1. No painel do Cloudflare, abra **Workers & Pages**, escolha a aba **Pages** e importe o repositório `PHPacheco/Raspagem` do GitHub.
2. Para validar a versão entregue, selecione a branch `codex/panela-aberta`. Em um projeto Pages já existente, use a URL de prévia dessa branch. Configure **Framework preset** como `None`, **Root directory** como `chatbot-web`, **Build command** como `exit 0` e **Build output directory** como `public`. O repositório já contém o catálogo usado pela função. [Configuração de deploy](https://developers.cloudflare.com/pages/get-started/git-integration/) · [Deploy de HTML com Pages Functions](https://developers.cloudflare.com/pages/framework-guides/deploy-anything/)
3. Após o primeiro deploy, abra **Settings → Bindings → Add → Workers AI** e use `AI` como nome. Escolha o ambiente correspondente à URL que pretende testar, **Preview** ou **Production**, e publique novamente. O Wrangler está configurado para desenvolvimento local e o painel é a fonte de configuração dos ambientes publicados. [Bindings do Pages](https://developers.cloudflare.com/pages/functions/bindings/#workers-ai)
4. Abra a URL gerada pelo Cloudflare, refaça o roteiro local e confira que a resposta apresenta uma explicação natural em português. Confira também o modo retornado pela rota. Execute este comando substituindo a URL pela sua:

```powershell
npm run verify -- https://SEU-PROJETO.pages.dev --require-ai
```

O comando compara a primeira receita, a quantidade de ingredientes faltantes e a latência no modo por regras e no modo automático. A opção `--require-ai` exige `mode: "ai"` nos cenários com sugestões. Se aparecer `mode: "rules"` no modo automático, confira o binding `AI` no ambiente correto e redeploy. O caso sem correspondência pode responder por regras mesmo com o binding ativo. Guarde a tabela e a URL como evidências da entrega.

Para usar Workers AI durante a execução local, autentique-se com `npx wrangler login` e inicie o servidor com `npm run dev -- --port 8788 --ai AI`. Cada requisição faz até duas chamadas de inferência. Verifique os limites da sua conta e a latência na prévia. [Cloudflare Workers AI](https://developers.cloudflare.com/pages/functions/bindings/#workers-ai)

## Como funciona

A Pages Function `POST /api/chat` importa 120 receitas de um JSON empacotado com o código. O SQLite é usado na preparação local. A busca reconhece ingredientes normalizados em português, calcula a cobertura de itens principais e aplica as exclusões e o tempo máximo antes de pontuar. Preferências como rapidez e baixo custo recebem peso quando a fonte fornece esses dados. O contexto da conversa fica na aba atual e acompanha as requisições.

O fluxo do Colab da Aula 12 inspira a recuperação de opções antes da geração. Em produção, o Qwen `@cf/qwen/qwen3.8-27b` é chamado pelo binding do Workers AI, com temperatura de 0,2, raciocínio baixo, resposta curta e validação de JSON no servidor. O modelo pode interpretar preferências, corrigir erros ortográficos simples e selecionar uma receita entre os candidatos elegíveis. O servidor valida o ID e monta os cartões a partir do catálogo. Em caso de erro, tempo limite ou resposta inválida, a recomendação por regras continua disponível. [Colab da Aula 12](https://colab.research.google.com/drive/1KTR9f7OeKopyU2Gh7zjW1P6rIR4crfMg?usp=sharing) · [Qwen no Workers AI](https://developers.cloudflare.com/workers-ai/models/qwen3.8-27b/)

## Estimativas nutricionais e atualização do catálogo

O piloto cobre **10 das 120 receitas**. O cálculo usa alimentos SR Legacy da USDA FoodData Central, medidas domésticas revisadas e o número de porções da receita original. As hipóteses de peso e as variantes estão registradas em [nutrition-mapping.json](scripts/data/nutrition-mapping.json). Quando faltam dados de peso ou de rendimento, a receita continua disponível e a estimativa fica indisponível. Para restrições alimentares, confira sempre a fonte e os rótulos de produtos compostos.

O arquivo nutricional inicial veio do CSV oficial da USDA. Os endereços originais das receitas foram recuperados dos HTML salvos e estão em [recipe-sources.json](scripts/data/recipe-sources.json). Para regenerar o catálogo com os dados versionados, execute na pasta `chatbot-web`:

```powershell
python scripts/export_catalog.py
```

Para atualizar com a API, obtenha sua chave no [FoodData Central](https://fdc.nal.usda.gov/api-guide/) e defina `USDA_API_KEY` apenas no ambiente local. Em seguida:

```powershell
python scripts/usda_nutrition.py
python scripts/export_catalog.py
```

O comando `usda_nutrition.py --sr-legacy-zip caminho/arquivo.zip` também aceita o [CSV oficial de SR Legacy](https://fdc.nal.usda.gov/download-datasets/). O chat em produção usa o JSON gerado e dispensa chave USDA no Cloudflare.

## Avaliação da Unidade 4

| Técnica | Uso na aplicação |
| --- | --- |
| LLM | Qwen por Workers AI para interpretação, ordenação e linguagem da resposta. |
| Prompt engineering e saída estruturada | Dois prompts em português com validação dos campos, IDs e limites do texto. |
| RAG e recuperação de informação | Busca lexical no catálogo da disciplina e geração condicionada aos candidatos recuperados. |
| Agentes e integração com ferramentas | A seleção e a consulta aos dados seguem o fluxo fixo implementado na função. |
| Modelos locais ou quantizados | Os Colabs são referência didática. A aplicação usa inferência remota. |
| Multimodalidade | Entrada e saída textuais. |
| Outras técnicas | Normalização lexical, sinônimos, filtros por regras e cálculo de cobertura. |

No Wrangler local, os quatro cenários HTTP recuperaram a panqueca sem itens faltantes, mantiveram contexto e limite de tempo, distinguiram os dois tipos de leite e pediram dados adicionais na ausência de correspondência. A ordenação por IA, a rejeição de IDs inventados e a resposta por regras passaram nos testes com um modelo simulado. A comparação com o Qwen real e a latência da prévia dependem da execução do roteiro no ambiente Cloudflare configurado.

O desenvolvimento usou Codex para implementação, revisão e testes de catálogo, nutrição, ranking e integração. A página, a tabela de avaliação e a URL de publicação compõem a documentação da demonstração.
