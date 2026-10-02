# Changelog

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
