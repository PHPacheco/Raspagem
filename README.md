# Coleta acadêmica de receitas

Projeto didático para estudar raspagem de HTML, normalização de dados, SQLite e análise textual em um notebook Jupyter com outputs prontos.

## Aviso de conformidade

O coletor se identifica como:

```text
AcademicRecipeCollector/1.0 (uso acadêmico; contato: mspiess@furb.br)
```

Por padrão, ele não acessa URLs `/recipe/`. A execução real dessas páginas exige autorização específica e, como o `robots.txt` atual pode desautorizá-las, o override só é aceito junto com a flag de autorização:

```text
--allow-authorized-recipe-pages --override-robots-with-permission
```

Não use essas flags sem autorização escrita. Para desenvolver e testar, use as fixtures locais.

## Instalação

No Windows CPython, o ambiente virtual normalmente usa `Scripts`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Neste workspace o Python é MSYS2, então o ambiente usa `bin`:

```powershell
python -m venv .venv
.\.venv\bin\python.exe -m pip install -r requirements.txt
```

## Usar dados de fixture

Este comando cria `data/recipes.sqlite` com uma página de categoria e uma receita de exemplo, sem acessar a internet:

```powershell
.\.venv\bin\python.exe -m scraper fixture
```

## Descobrir apenas links de categoria

Essa opção acessa a categoria, respeita `robots.txt` e não acessa páginas de receita:

```powershell
.\.venv\bin\python.exe -m scraper collect `
  --category-url https://www.tudogostoso.com.br/categorias/1004-carnes `
  --max-pages 1 `
  --discover-only
```

## Coleta autorizada

Somente após a autorização adequada:

```powershell
.\.venv\bin\python.exe -m scraper collect `
  --category-url https://www.tudogostoso.com.br/categorias/1004-carnes `
  --max-pages 2 `
  --allow-authorized-recipe-pages `
  --override-robots-with-permission
```

As execuções geram logs JSONL em `logs/`. O banco armazena detalhes normalizados, não snapshots HTML.

## Limpeza e preparação dos textos

O projeto mantém o texto bruto extraído e registra versões derivadas na tabela `text_preparations`.
O pipeline aplicado segue as etapas da aula de PLN:

- remoção de HTML residual, menus e URLs;
- normalização de espaços, caixa e acentos;
- remoção de pontuação, símbolos e emojis para a versão tokenizada;
- tokenização por palavras;
- remoção seletiva de stopwords em português, preservando negação;
- stemming leve;
- lematização heurística para termos comuns do domínio;
- chaves de duplicidade literal e quase duplicidade;
- versão do pipeline e lista de transformações aplicadas.

Para reconstruir essas versões em um banco já existente:

```powershell
.\.venv\bin\python.exe -m scraper prepare-db
```

## Representação e análise textual

Depois da preparação, o projeto também implementa o processo da aula sobre transformar textos em dados analisáveis:

```text
Textos -> preparação -> TF-IDF -> matriz documento x termo
```

A partir da matriz, o projeto calcula:

- termos principais de cada receita;
- similaridade por cosseno entre receitas;
- clusters com K-Means simples;
- coordenadas 3D por projeção linear para visualização.

Para gerar essa etapa no banco:

```powershell
.\.venv\bin\python.exe -m scraper analyze-texts
```

O resultado fica nas tabelas `text_analysis_runs`, `document_vectors`, `document_term_weights` e `document_similarities`.
No notebook, a seção de análise textual mostra um mapa 3D das receitas, além da leitura didática dos termos e vizinhos.

## Embeddings por contexto

A etapa seguinte implementa uma versão didática da aula sobre Word2Vec e embeddings modernos.
O projeto aprende embeddings densos locais a partir da hipótese distribucional:

```text
palavras em contextos semelhantes -> vetores próximos
```

O fluxo usado é:

- janelas de contexto sobre os tokens preparados;
- contagens de coocorrência;
- ponderação PPMI;
- projeção densa determinística;
- embedding de cada receita pela média dos vetores de seus termos;
- similaridade por cosseno entre embeddings de receitas.

Para gerar essa etapa no banco:

```powershell
.\.venv\bin\python.exe -m scraper build-embeddings
```

O resultado fica nas tabelas `embedding_runs`, `word_embeddings`, `document_embeddings` e `embedding_similarities`.
No notebook, a aula 7 mostra embeddings, vizinhos por similaridade densa, busca semântica e uma composição contextual didática. Essa composição demonstra `palavra + contexto -> vetor`, mas não é BERT nem um Transformer.

## Classificação textual — aula 8

O projeto implementa um baseline supervisionado com Naive Bayes multinomial. O alvo pode ser a dificuldade ou o custo da receita. O pipeline inclui divisão estratificada entre treino e teste, probabilidades, matriz de confusão, acurácia, precisão, revocação e F1.

```powershell
.\.venv\bin\python.exe -m scraper classify-texts --target difficulty
```

Quando o corpus não possui classes ou exemplos suficientes, a execução registra essa limitação e não publica métricas inválidas. Os resultados ficam em `classification_runs`, `classification_predictions` e `classification_metrics`.

## Análise linguística — aula 9

A etapa 9 produz informação explicitamente estruturada para o domínio de receitas:

- dependências sintáticas rasas de instruções;
- sentimento por léxico, negação, intensidade e aspectos;
- entidades de ingrediente, utensílio, categoria, quantidade, unidade, duração e temperatura;
- relações em triplas, incluindo relações estruturais e pares ação–objeto.

```powershell
.\.venv\bin\python.exe -m scraper analyze-linguistics
```

Os métodos são baselines determinísticos e interpretáveis, não substitutos de um parser neural, BERT ou NER treinado. Os resultados ficam nas tabelas `linguistic_analysis_runs`, `syntactic_dependencies`, `sentiment_analyses`, `named_entities` e `semantic_relations`.

## Gerar e abrir o notebook

```powershell
.\.venv\bin\python.exe -m scraper export-notebook
```

Esse comando gera `notebooks\Trabalho PLN.ipynb` com outputs prontos. O fluxo oficial de visualização não usa mais página web/Streamlit.

Para atualizar tudo antes de gerar o notebook:

```powershell
.\.venv\bin\python.exe -m scraper analyze-texts
.\.venv\bin\python.exe -m scraper build-embeddings
.\.venv\bin\python.exe -m scraper classify-texts --target difficulty
.\.venv\bin\python.exe -m scraper analyze-linguistics
.\.venv\bin\python.exe -m scraper export-notebook
```

O notebook mantém os filtros em forma de variáveis editáveis, além das tabelas, detalhes das receitas, preparação textual, gráfico 3D, TF-IDF, embeddings, classificação e extração de informação.

## Relatório web separado

O relatório estático fica isolado em `relatorio-web\`. Essa pasta não importa módulos Python, não executa análises e contém apenas HTML, CSS, documentação e um atalho próprio. O notebook continua sendo a interface executável da análise.

No Windows, abra o relatório com:

```text
relatorio-web\abrir_relatorio.bat
```

## Testes

```powershell
.\.venv\bin\python.exe -m pytest -q
```

## Atalho no Windows

O arquivo `bats\coletar_receitas.bat` cria o ambiente virtual quando necessário e instala as dependências mínimas da coleta (`beautifulsoup4` e `requests`) se elas ainda não estiverem disponíveis.

```text
bats\coletar_receitas.bat
bats\coletar_receitas.bat fixture
bats\coletar_receitas.bat --max-pages 2 --discover-only
```

Sem argumentos, o BAT executa o modo seguro de descoberta.

Para visualizar as implementações mais recentes sem decorar os comandos, use:

```text
bats\visualizar_novidades.bat
```

Esse atalho atualiza a preparação dos textos, TF-IDF, projeção 3D, embeddings da aula 7, classificação da aula 8 e análise linguística da aula 9. Depois exporta `notebooks\Trabalho PLN.ipynb` com outputs prontos e tenta abrir o notebook no VS Code ou no aplicativo padrão. Se o banco `data\recipes.sqlite` ainda não existir, ele carrega a fixture local antes de gerar o notebook.
