"""Nível 2: assistente de documentos (extração, validação, planilha, checklist e cobrança).

Fluxo: XML de NF-e lido sem IA → PDF e imagem pela Claude API com saída estruturada →
validação (CNPJ/CPF, datas, soma) → planilha com coluna "revisar". Nada é lançado sem
o contador aprovar.
"""
