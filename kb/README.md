# Base de conhecimento (kb/)

Tudo o que o atendente sabe sobre o negócio está nesta pasta. Se não estiver aqui, ele deve dizer "Não sei essa informação" e oferecer uma pessoa da equipe.

## Como o cliente mantém a base

1. **Formato:** Markdown simples. Um arquivo por assunto (`01_sobre_a_clinica.md`, `02_servicos_e_precos.md`...). Frases curtas, uma informação por linha, valores com "R$".
2. **O que entra:** horários, endereço, serviços, preços, convênios, preparo genérico, políticas, perguntas frequentes.
3. **O que NÃO entra:** dados de pacientes, senhas, chaves, informações internas que não podem ser ditas ao público, orientação médica individual.
4. **Quem aprova:** o responsável do cliente lê e aprova cada mudança antes de ir ao ar. Registre a aprovação no histórico abaixo.
5. **Como pedir mudança:** o cliente manda o texto novo por WhatsApp ou e-mail; o desenvolvedor edita, roda os evals (`python evals/rodar.py`) e publica.
6. **Revisão:** todo mês, use a seção "Perguntas que terminaram em não sei" do relatório mensal para decidir o que acrescentar.

## Tamanho e custo

A base inteira vai no prompt com cache. Até ~50 mil tokens (cerca de 150 páginas de texto) funciona bem e barato no Haiku. Acima de 100 mil tokens o preço do Haiku 5.5 sobe de faixa: aí é hora de resumir ou dividir.

## Histórico de versões

| Versão | Data | O que mudou | Aprovado por |
|---|---|---|---|
| 1.0 | (preencher) | Base inicial de exemplo (Clínica Exemplo, dados fictícios) | (preencher) |
