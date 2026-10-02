# Toyota | Gestão Inteligente de Estoque

Aplicativo em **Streamlit** adaptado às bases reais de estoque e vendas Toyota fornecidas para o projeto.

## O que o sistema entrega

- cobertura consolidada por **regional** e **loja**;
- análise de veículo por **família → modelo → cor**;
- identificação de **ruptura/falta**, **estoque adequado**, **estoque elevado**, **excesso transferível** e **sem giro**;
- sugestões de transferência entre lojas;
- prioridade para transferências dentro da mesma regional;
- primeiro pareamento pela **mesma família + modelo + cor**;
- segunda oportunidade por **família + modelo com cor alternativa**, quando habilitada;
- exportação de relatório Excel com todas as análises.

## Layout Toyota reconhecido automaticamente

### Estoque

A versão atual reconhece diretamente:

- `Regional`
- `Filial`
- `Pátio`
- `Familia`
- `Modelo`
- `Cor`
- `Chassi`

Cada linha é tratada como **1 veículo em estoque**.

### Histórico de vendas

- `Regional`
- `Filial_vendedor`
- `Familia`
- `Modelo`
- `Cor`
- `Chassi`
- `Data Venda`

Cada linha é tratada como **1 veículo vendido**.

Se o arquivo não estiver nesse layout, o sistema abre um mapeamento manual de colunas.

## Tratamentos feitos automaticamente

### Família

A base recebida possui cadastros como:

- `TOY HILUX` e `HILUX`
- `TOY COROLLA` e `COROLLA`
- `TOY COROLLA CROSS` e `COROLLA CROSS`

O sistema remove automaticamente o prefixo `TOY ` para que uma mesma família não seja analisada como dois produtos diferentes.

### Chassi

Quando a base está em nível de chassi, duplicidades acidentais são eliminadas antes dos cálculos.

### Pátio / status

Os pátios podem ser excluídos da cobertura pelo painel lateral. No padrão atual, `DEMONSTRACAO` vem excluído por padrão e `TRANSITO` permanece considerado.

### Marca

O sistema identifica `TOYOTA` e `LEXUS` e permite selecionar uma ou ambas.

## Regras de cobertura

O período padrão é **todo o intervalo existente na base de vendas**. Também é possível selecionar 30, 60, 90, 120 ou 180 dias.

- `Média diária = vendas no período / dias efetivamente analisados`
- `Cobertura = estoque / média diária`
- `Estoque alvo = média diária × cobertura alvo`
- `Estoque mínimo = média diária × cobertura mínima`
- `Estoque máximo = média diária × cobertura máxima`

Parâmetros iniciais:

- cobertura mínima: **30 dias**;
- cobertura alvo: **45 dias**;
- cobertura máxima: **75 dias**.

Todos podem ser alterados na barra lateral.

## Classificação

- **RUPTURA**: houve venda no período e o estoque atual é zero;
- **FALTA**: cobertura abaixo da mínima;
- **ADEQUADO**: cobertura dentro da faixa;
- **ELEVADO**: cobertura acima da máxima, mas sem unidade excedente removível até o alvo;
- **EXCESSO**: há quantidade efetivamente removível mantendo o estoque alvo;
- **SEM GIRO**: existe estoque, mas não houve venda no período analisado.

## Transferências

O sistema calcula a necessidade das lojas abaixo da cobertura mínima e a disponibilidade dos doadores acima do estoque alvo.

Ordem de tentativa:

1. mesma **família + modelo + cor**;
2. mesma **família + modelo** com cor alternativa, se habilitado;
3. dentro de cada tentativa, prioriza a **mesma regional**;
4. mantém no doador pelo menos o estoque alvo e a reserva mínima configurada.

Sugestões de cor alternativa aparecem como **AVALIAR**, enquanto pareamentos exatos aparecem como **RECOMENDADA**.

## Executar localmente

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Publicar no GitHub + Streamlit Community Cloud

1. Crie um repositório no GitHub.
2. Envie a pasta completa do projeto.
3. Mantenha `app.py` e `requirements.txt` na raiz.
4. No Streamlit Community Cloud, conecte o repositório.
5. Selecione `app.py` como arquivo principal e faça o deploy.

## Estrutura

```text
toyota_estoque_app/
├── app.py
├── requirements.txt
├── README.md
├── .streamlit/
│   └── config.toml
├── src/
│   ├── __init__.py
│   ├── analysis.py
│   └── io_utils.py
└── examples/
    ├── estoque_exemplo.csv
    └── vendas_exemplo.csv
```

## Evoluções recomendadas

- metas de cobertura específicas por família/modelo;
- distância e custo logístico entre lojas;
- tratamento diferenciado para trânsito x físico x demonstração;
- pedidos/cotas da montadora e cobertura pós-pedido;
- aprovação de transferências e trilha de decisão;
- integração automática com SharePoint/OneDrive;
- histórico diário da cobertura e das recomendações.
