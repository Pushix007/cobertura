# Changelog

## v2.1 - Correção de leitura de datas

- corrige erro de overflow ao carregar `Data Venda` já reconhecida pelo Excel/pandas como data;
- preserva colunas `datetime64` antes da tentativa de conversão numérica;
- mantém suporte a datas em texto, serial do Excel e timestamps Unix;
- validado com as bases reais `Estoque Toyota.xlsx` e `Histórico Toyota.xlsx`.

## v2.0 - Bases Toyota reais

- reconhecimento automático das colunas `Filial`, `Pátio` e `Filial_vendedor`;
- 1 linha = 1 chassi para estoque e vendas;
- normalização automática de `TOY HILUX`/`HILUX`, `TOY COROLLA`/`COROLLA` etc.;
- seleção Toyota/Lexus;
- exclusão parametrizável de pátios/status, com `DEMONSTRACAO` excluído por padrão;
- período completo da base como padrão, usando os dias efetivamente disponíveis;
- criticidade principal calculada por loja + família + modelo;
- cor usada como camada de mix para a sugestão de transferência;
- transferência sequencial sem reutilizar o mesmo saldo;
- pareamento exato classificado como `RECOMENDADA` e cor alternativa como `AVALIAR`;
- aba de qualidade da base;
- exportação com detalhamento por loja/modelo e loja/modelo/cor.
