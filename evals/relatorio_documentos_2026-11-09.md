# Relatório de evals de documentos – 09/11/2026

- Modo: **offline** · modelo: `claude-haiku-5-5` · ambíguo: `claude-sonnet-5-5`
- Resultado: **12/12 aprovados** · 5 documentos na coluna "revisar"
- Custo estimado: US$ 0.0136 (R$ 0.0750); XML de NF-e não usa IA
- nfelib disponível: sim
- Atenção: modo offline usa um cliente falso que lê o texto embutido nos arquivos de exemplo; valida o pipeline, não a qualidade do modelo.

| Caso | Resultado | Origem | Categoria | Valor | Revisar | Modelos | Falhas | Custo US$ |
|---|---|---|---|---|---|---|---|---|
| xml_nfe_papelaria | OK | xml-nfelib | nota_fiscal_produto | 70.00 | não | - | - | 0.00000 |
| xml_nfe_com_frete | OK | xml-nfelib | nota_fiscal_produto | 320.00 | não | - | - | 0.00000 |
| xml_nfce_cnpj_invalido | OK | xml-nfelib | cupom_fiscal | 45.90 | sim | - | - | 0.00000 |
| pdf_recibo_aluguel_cpf | OK | claude | recibo | 1800.00 | não | haiku-5-5 | - | 0.00027 |
| pdf_nfse_servico | OK | claude | nota_fiscal_servico | 770.00 | não | haiku-5-5 | - | 0.00029 |
| pdf_extrato_bancario | OK | claude | extrato_bancario | 12345.67 | não | haiku-5-5 | - | 0.00027 |
| pdf_soma_divergente | OK | claude | nota_fiscal_produto | 160.00 | sim | haiku-5-5 | - | 0.00029 |
| img_cupom_material | OK | claude | cupom_fiscal | 149.80 | não | haiku-5-5 | - | 0.00029 |
| img_recibo_amassado_sem_data | OK | claude | recibo | 120.00 | sim | haiku-5-5, sonnet-5-5 | - | 0.00572 |
| img_boleto_ambiguo_roteado | OK | claude | boleto | 389.40 | não | haiku-5-5, sonnet-5-5 | - | 0.00592 |
| ilegivel_foto_borrada | OK | claude | outro | 0.00 | sim | haiku-5-5 | - | 0.00026 |
| ilegivel_pdf_escaneado | OK | claude | outro | 0.00 | sim | haiku-5-5 | - | 0.00025 |

## Motivos de revisão

- xml_nfce_cnpj_invalido: CNPJ inválido (90314159000183)
- pdf_soma_divergente: soma dos itens (R$ 150,00) diferente do total (R$ 160,00)
- img_recibo_amassado_sem_data: baixa confiança em data_emissao; data de emissão ausente
- ilegivel_foto_borrada: ilegível ou não reconhecido: sem texto legível
- ilegivel_pdf_escaneado: ilegível ou não reconhecido: sem texto legível

## Painel da competência 2026-10

- **Padaria Pão Bom (fictícia): faltam extrato do Banco Exemplo** · planilha `evals/saida_documentos/padaria-pao-bom.xlsx`
  - Prévia da cobrança (template `documentos_pendentes`, só texto, não enviada):
    > Olá, João! Para fecharmos a contabilidade de outubro da Padaria Pão Bom (fictícia), ainda faltam: extrato do Banco Exemplo.
    > Você pode enviar foto ou PDF por aqui até 10/11. Obrigado!
- **Studio Bela Forma (fictício): faltam 1 de 2 notas de serviço emitidas** · planilha `evals/saida_documentos/studio-bela-forma.xlsx`
  - Prévia da cobrança (template `documentos_pendentes`, só texto, não enviada):
    > Olá, Carla! Para fecharmos a contabilidade de outubro da Studio Bela Forma (fictício), ainda faltam: 1 de 2 notas de serviço emitidas.
    > Você pode enviar foto ou PDF por aqui até 10/11. Obrigado!
