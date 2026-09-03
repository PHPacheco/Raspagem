# Estudo da implementação: coleta de receitas

Este documento explica como o projeto foi construído, quais tecnologias foram usadas e como os dados percorrem o sistema.

## 1. Objetivo

O projeto coleta receitas de uma categoria do TudoGostoso, começando pela seção **Receitas recomendadas**, e salva os dados em um banco SQLite para consulta em uma aplicação local.

O fluxo geral é:

```text
Categoria
   ↓
Links das receitas recomendadas
   ↓
Páginas individuais das receitas
   ↓
Parser e normalização
   ↓
SQLite
   ↓
Aplicação Streamlit
```

A quantidade de páginas é configurável. A primeira página é a URL da categoria; as páginas seguintes usam o parâmetro `?page=N`.

## 2. Tecnologias

### Python

É a linguagem principal porque possui bibliotecas simples para HTTP, HTML, banco de dados e prototipação de interfaces.

### Requests

Responsável por fazer requisições HTTP. O projeto usa uma sessão (`requests.Session`) para manter cabeçalhos comuns e configurar o identificador do agente.

### BeautifulSoup

Lê o HTML e permite localizar títulos, links, listas e seções. O parser procura primeiro elementos semânticos, como títulos e listas, em vez de depender somente de classes CSS que podem mudar.

### SQLite

É um banco armazenado em arquivo, sem necessidade de instalar um servidor. A tabela principal é `recipes`; ingredientes, utensílios e etapas ficam em tabelas separadas porque uma receita pode ter vários itens.

### Streamlit

Cria a interface web local a partir de Python. A aplicação permite buscar receitas, filtrar resultados e abrir os detalhes armazenados no banco.

## 3. Etapa de conformidade

O cliente HTTP utiliza o seguinte `User-Agent`:

```text
AcademicRecipeCollector/1.0 (uso acadêmico; contato: mspiess@furb.br)
```

Antes de consultar o site, ele verifica o `robots.txt`. Por segurança, páginas `/recipe/` ficam bloqueadas por padrão. O modo autorizado exige as duas flags abaixo:

```text
--allow-authorized-recipe-pages --override-robots-with-permission
```

Essas flags só devem ser usadas quando houver autorização específica. Identificar o agente não equivale a obter autorização para copiar ou republicar conteúdo.

Quando não há autorização, o projeto oferece duas alternativas:

- `--discover-only`: consulta somente a categoria e não acessa páginas de receitas;
- `fixture`: usa HTML local de teste, sem acessar a internet.

## 4. Descoberta das receitas

O módulo `scraper/category_parser.py` executa as seguintes operações:

1. Lê o HTML da categoria.
2. Localiza o título `Receitas recomendadas`.
3. Procura links de receitas dentro dessa seção.
4. Converte links relativos em URLs completas.
5. Extrai o ID da receita da URL.
6. Preserva título, página e posição da recomendação.
7. Remove links duplicados durante a coleta dos detalhes.
8. Verifica se existe uma próxima página.

O parser aceita até 15 recomendações por página, conforme o formato observado no site. O limite de páginas é controlado pelo argumento `--max-pages`.

## 5. Extração de uma receita

O módulo `scraper/recipe_parser.py` transforma o HTML da receita em um objeto `RecipeData`.

Os dados principais são:

- ID e título;
- URL original;
- avaliação média e quantidade de avaliações;
- tempo em minutos e texto original do tempo;
- dificuldade;
- custo como rótulo, por exemplo `Custo médio`;
- quantidade de porções;
- ingredientes;
- utensílios;
- etapas do modo de preparo;
- categorias relacionadas;
- data de coleta e versão do parser.

O parser tenta encontrar primeiro um bloco JSON-LD do tipo `Recipe`. Caso algum campo não esteja disponível ali, usa o HTML visível como fallback.

Os valores numéricos são normalizados:

```text
"4,5 / 5"          → 4.5
"1.548 avaliações" → 1548
"25min"            → 25 minutos
```

O texto original também é preservado quando isso é útil, como em `prep_time_raw`. Campos ausentes não recebem valores inventados: são armazenados como `NULL` e registrados em `issues`.

## 6. Modelo do banco

O arquivo `schema.sql` cria as seguintes tabelas:

| Tabela | Finalidade |
|---|---|
| `scrape_runs` | Histórico de cada execução |
| `recipes` | Dados principais da receita |
| `ingredients` | Ingredientes ordenados |
| `utensils` | Utensílios ordenados |
| `preparation_steps` | Etapas ordenadas |
| `categories` | Categorias relacionadas |
| `recipe_categories` | Relação entre receita e categoria |
| `category_listings` | Página e posição em que a receita foi recomendada |

O ID do site é usado como chave da receita. Assim, se uma mesma receita aparece em duas páginas ou em duas execuções, os detalhes não são duplicados.

As gravações usam consultas parametrizadas e transações. Ao atualizar uma receita, as listas antigas de ingredientes, utensílios, etapas e categorias são substituídas pelas listas mais recentes.

## 7. Interface da aplicação

O arquivo `app.py` abre `data/recipes.sqlite` e oferece:

- busca por título, ingredientes, utensílios, etapas e categorias;
- normalização de acentos para buscas em português;
- filtro por dificuldade;
- filtro por custo;
- filtro por tempo máximo;
- filtro por avaliação mínima;
- filtro por categoria relacionada;
- tabela resumida de resultados;
- visualização detalhada da receita;
- link para a página original.

A busca atual é textual. TF-IDF, embeddings e recomendação semântica podem ser adicionados depois como uma etapa específica de PLN.

## 8. Como executar

### Criar ambiente e instalar dependências

Em uma instalação comum do Python no Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Neste workspace MSYS2, o executável fica em `bin`:

```powershell
python -m venv .venv
.\.venv\bin\python.exe -m pip install -r requirements.txt
```

### Carregar fixture local

```powershell
.\.venv\bin\python.exe -m scraper fixture
```

Isso cria `data/recipes.sqlite` sem fazer requisições externas.

### Descobrir links da categoria

```powershell
.\.venv\bin\python.exe -m scraper collect `
  --category-url https://www.tudogostoso.com.br/categorias/1004-carnes `
  --max-pages 1 `
  --discover-only
```

### Coleta autorizada

Somente depois de obter autorização específica:

```powershell
.\.venv\bin\python.exe -m scraper collect `
  --category-url https://www.tudogostoso.com.br/categorias/1004-carnes `
  --max-pages 2 `
  --allow-authorized-recipe-pages `
  --override-robots-with-permission
```

### Abrir a aplicação

```powershell
streamlit run app.py
```

### Executar os testes

```powershell
.\.venv\bin\python.exe -m pytest -q
```

## 9. Testes implementados

Os testes usam fixtures locais para não depender do site durante a execução:

- extração das 15 receitas recomendadas;
- exclusão de links fora da seção correta;
- paginação;
- leitura dos campos da receita;
- preferência por JSON-LD;
- tratamento de campos ausentes;
- busca sem sensibilidade a acentos;
- filtro por categoria;
- comportamento de upsert no SQLite;
- bloqueio de páginas de receita sem autorização.

## 10. Pontos para estudar depois

Depois de compreender o coletor, os próximos exercícios possíveis são:

1. Extrair nomes de ingredientes em campos separados.
2. Criar estatísticas de ingredientes mais frequentes.
3. Comparar receitas por similaridade TF-IDF.
4. Criar um recomendador baseado em ingredientes informados pelo usuário.
5. Aplicar tokenização, remoção de stopwords e lematização em português.

