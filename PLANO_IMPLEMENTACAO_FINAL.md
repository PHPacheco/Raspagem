# Plano de implementação final do Panela Aberta

O Panela Aberta vai receber ingredientes e preferências em linguagem natural e indicar uma receita do catálogo do projeto. A resposta vai mostrar por que a receita foi escolhida, o que já está disponível, o que falta, o tempo de preparo quando conhecido e o link para a fonte. Quando houver dados suficientes, também vai mostrar calorias, proteínas, carboidratos e gorduras estimadas por porção.

A entrega segue a **Modalidade B — Aplicação web funcional** da Mostra Virtual de PLN. A interface e a rota `POST /api/chat` partem do protótipo anterior. O SQLite local contém 120 receitas e guarda ingredientes como texto livre.

## Estado da implementação

O chatbot já usa as 120 receitas reais do catálogo. As 10 receitas do piloto nutricional têm estimativas da USDA. O ranking e o fluxo HTTP passaram na validação local, incluindo a integração simulada do Qwen. A chamada ao Qwen real e a validação da URL pública seguem o [roteiro de publicação e teste](chatbot-web/README.md).

## Arquitetura

```text
Preparação local
  SQLite → normalização dos ingredientes → catálogo JSON
  USDA FoodData Central → cálculo por porção → nutrientes no mesmo JSON

Produção
  Navegador → Cloudflare Pages → POST /api/chat
                                   ├─ Catálogo JSON incluído no deploy
                                   └─ Workers AI → interpretação e resposta
```

O SQLite é a fonte local para gerar o arquivo. Em produção, a Pages Function importa o JSON somente para leitura. Atualizações do catálogo ou dos nutrientes são feitas regenerando o arquivo e publicando uma nova versão. O contexto recente da conversa fica na sessão do navegador e segue de forma limitada em cada requisição. [Cloudflare Pages Functions](https://developers.cloudflare.com/pages/functions/get-started/)

## 1. Exportar o catálogo e substituir a demonstração

- Criar um script reproduzível que leia `data/recipes.sqlite` e gere `chatbot-web/functions/data/recipes.json`. Validar primeiro com 10 receitas e ampliar para as receitas elegíveis do catálogo.
- Incluir ID estável, título, URL, ingredientes originais e normalizados, porções e tempo quando disponíveis. Preservar as medidas originais para o cálculo nutricional e levar ao site apenas conteúdo autorizado para divulgação. Quando o modo de preparo ficar na fonte, oferecer um link direto.
- Substituir os exemplos fixos do endpoint pelo JSON. Na página publicada, mostrar uma mensagem de erro quando o endpoint estiver indisponível.

**Aceite.** O Wrangler executa localmente a rota com receitas reais, IDs e fontes válidos, a partir de um catálogo que pode ser regenerado.

## 2. Implementar o ranking inicial

- Normalizar acentos, plurais e sinônimos em português. Comparar ingredientes inteiros, incluindo expressões como “leite de coco”, considerando negações como “não tenho leite”.
- Aplicar exclusões explícitas antes da pontuação. Priorizar o aproveitamento dos ingredientes disponíveis e penalizar a falta de itens essenciais. Usar dados conhecidos para ponderar preferências como tempo de preparo e custo.
- Retornar uma recomendação principal e, quando fizer sentido, até duas alternativas. Com poucos dados ou sem correspondência suficiente, perguntar por um ingrediente adicional ou por uma preferência que ajude a escolher.

**Aceite.** O ranking é reproduzível e a justificativa corresponde aos ingredientes, às restrições e aos dados da receita.

## 3. Integrar calorias e macronutrientes

- Usar a **USDA FoodData Central**, conforme a opção discutida anteriormente. Um script local busca alimentos e consulta seus detalhes. Registrar em arquivo os mapeamentos revisados entre ingredientes em português e IDs do FoodData Central, diferenciando casos como ingrediente cru e cozido. Guardar a chave fora do Git. [Guia da API FoodData Central](https://fdc.nal.usda.gov/api-guide/)
- Converter as medidas da receita para gramas quando houver uma equivalência confiável para aquele ingrediente. Multiplicar os valores por 100 g pela quantidade usada, somar e dividir pelo rendimento em porções. Gravar no JSON a data da consulta, a fonte e as estimativas por porção.
- Revisar manualmente as 10 receitas iniciais e medir a cobertura nutricional ao ampliar o catálogo. Quando faltar uma quantidade relevante, um alimento equivalente, um nutriente ou o rendimento necessário, mostrar “Estimativa indisponível” para o resultado afetado. Diferenciar dados ausentes de valores iguais a zero.

**Aceite.** Os valores exibidos podem ser refeitos a partir de gramagens, rendimento e IDs da USDA. O chat recomenda receitas normalmente usando o arquivo gerado, inclusive quando a API nutricional estiver indisponível.

## 4. Integrar a IA seguindo o fluxo do Colab

Os notebooks das aulas 11 e 12 executam Qwen no próprio Colab. O exercício de RAG da Aula 12 recupera contexto antes de gerar a resposta. No site, a proposta é aplicar esse fluxo com **Qwen no Cloudflare Workers AI**, começando por validar `@cf/qwen/qwen3.8-27b` em português e conferir latência e consumo. A Pages Function pode chamar o modelo usando `context.env.AI`. [Colab da Aula 11](https://colab.research.google.com/drive/1vrijrCl0cyP7gZ1RU4mRljeTyjf62BSm?usp=sharing) · [Colab da Aula 12](https://colab.research.google.com/drive/1KTR9f7OeKopyU2Gh7zjW1P6rIR4crfMg?usp=sharing) · [Modelo Qwen no Workers AI](https://developers.cloudflare.com/workers-ai/models/qwen3.8-27b/) · [Integração com Pages Functions](https://developers.cloudflare.com/pages/functions/bindings/#workers-ai)

- Usar saída estruturada para interpretar ingredientes disponíveis, exclusões e preferências. Reaproveitar o contexto recente em mensagens como “também tenho cebola”.
- Rodar o ranking no catálogo e apresentar ao modelo apenas os candidatos elegíveis e os dados que justificam a escolha. Permitir que ele reordene os melhores candidatos por preferências declaradas, como “algo rápido”, dentro dos critérios de compatibilidade. Exigir IDs válidos na resposta e validar novamente as exclusões no servidor.
- Usar a IA para redigir a explicação em português. A função monta os cartões de receita com os ingredientes, as fontes e os valores do catálogo. Se a IA demorar, falhar ou retornar uma saída inválida, usar o ranking original e uma explicação gerada pelo código.

**Aceite.** Uma preferência muda a ordem quando há evidência no catálogo. Toda recomendação aponta para uma opção elegível e o fluxo continua funcionando quando a chamada de IA falha.

## 5. Validar, publicar e entregar

- Comparar o ranking por regras com o ranking ajustado pela IA nos mesmos exemplos. Registrar acerto da primeira recomendação, quantidade de ingredientes essenciais em falta, respeito às exclusões e latência. Incluir ingredientes ambíguos, poucos ingredientes, continuação de conversa, ausência de estimativa nutricional e indisponibilidade da IA.
- Testar a prévia do Cloudflare em celular e desktop, incluindo teclado, mensagens de erro e reinício da conversa. Configurar o acesso ao Workers AI, limitar o tamanho das mensagens e das chamadas ao modelo e verificar se a URL pública responde ao fluxo completo. [Configuração do Cloudflare Pages com Wrangler](https://developers.cloudflare.com/pages/functions/wrangler-configuration/)
- Completar a página com título, autoria, descrição, instruções e exemplos. Atualizar o README com a URL pública, os passos de execução, o modelo, a forma de acesso, as configurações, as limitações e os resultados. Preencher o quadro de técnicas da Unidade 4 e registrar o uso auxiliar de IA conforme o enunciado. [Enunciado da Unidade 4](<C:/Users/AMD/Desktop/FURB/PLN/Implementação final/PLN_Trabalho_Unidade_4_Mostra_Virtual (1).pdf>)

**Aceite final.** Na URL pública, o usuário informa os ingredientes, recebe uma receita do catálogo com justificativa e fonte, e vê as estimativas nutricionais quando os dados são suficientes. O repositório contém as instruções e as evidências da avaliação.

## Primeira implementação

Exportar 10 receitas reais, ligar o JSON ao `/api/chat` e validar a recomendação por ingredientes antes de adicionar as duas integrações. Em paralelo, verificar o cálculo nutricional de uma receita com medidas claras e fazer uma chamada curta ao Qwen na prévia para confirmar o formato de resposta.
