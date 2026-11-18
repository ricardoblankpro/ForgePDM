# Vocabulário local de Fasteners em pt-BR

Consulta: 2026-11-18. Escopo: propostas determinísticas de descrição, sem
alterar especificações, cadastro de opções, identidade ou traduções aprovadas.
O fluxo de uso e revisão pertence ao [guia de idiomas](../../user/localization.md).

## Recursos e versões

- `src/forgepdm/domain/fastener_terms.json` continua sendo o mapa compartilhado
  de normas → tipo/família, versão 1, sem alteração de suas 99 entradas.
- `src/forgepdm/domain/fastener_locales/pt-BR.json` contém `schema_version`,
  `version`, `language`, fontes por grupo e os grupos `types`, `families`,
  `materials`, `finishes`, `descriptors`, `grades` e `messages`.
- Chaves são os termos canônicos ingleses. Valores são a apresentação local.
  Siglas, ligas, têmperas e marcas técnicas são entradas explícitas, mesmo quando
  o valor permanece igual à chave. Não há tradução por prefixo nem equivalência
  automática entre A2/304, A4/316 ou sistemas de revestimento.
- Para espanhol, adicionar um recurso irmão com o mesmo esquema e registrar
  seu caminho em `VOCABULARIES`; habilitar o idioma no serviço/UI continua sendo
  uma decisão separada. Nenhum idioma espanhol é habilitado neste incremento.
- A proveniência pt-BR conserva `provider=fastener-terms` e `version=1` do mapa e
  acrescenta `vocabulary_language` e `vocabulary_version`. Incrementar a versão
  do vocabulário quando seus textos mudarem. A proveniência inglesa permanece
  idêntica. Versões antigas salvas continuam legíveis, sem migração/reaprovação.

## Fontes

Os identificadores abaixo são os usados em `sources` no recurso. São referências
terminológicas; as escolhas editoriais e limites de inferência são do ForgePDM.
Não foram incorporados código, arquivos TS, imagens ou tabelas de catálogos.

| ID | Fonte e uso |
| --- | --- |
| fasteners-wb | [Fasteners Workbench, tradução pt-BR](https://github.com/shaise/FreeCAD_FastenersWB/blob/master/Resources/translations/fasteners_pt-br.ts). Consultada a cópia local da versão 0.5.43, SHA-256 `78aed461d0d9a5de907533f4a79616285e751c710c8f9206cac26ffd114df174`. Projeto sob GPL-2.0-or-later; referência sem cópia de código/arquivo. Inclui nomes de cabeças, porcas e o descritor cego; várias mensagens ainda são `unfinished`, que não foram tratadas como traduções. |
| ciser | [Catálogo de produtos Ciser](https://www.ciser.com.br/userfiles/downloads/catalogo-de-produtos-ciser-1.pdf), seção de porcas, folha 56c: diferencia o inserto de nylon da família autotravante. Consulta ao trecho indexado; o PDF integral excedeu o limite de leitura da ferramenta. |
| indufix-allen | [Catálogo de sextavado interno Indufix](https://www.indufix.com.br/pdf/Catalogo-Sextavado-Interno-INDUFIX.pdf), índice e folhas 21–22: nomes de cabeças e corpo com ressalto; [índice de produtos](https://www.indufix.com.br/sitemap/) distingue DIN 913/914/915/916 e arruela cônica DIN 6796. |
| fusopar | [Categorias Fusopar](https://www.fusopar.com.br/categorias): arruelas dentadas/lisas/mola prato, porcas calota/borboleta/quadrada e barras roscadas; materiais usuais. O catálogo técnico 2024 apareceu indexado, mas o endereço respondeu página não encontrada; a validação aqui usa as categorias acessíveis. |
| indufix-finishes | [Guia de acabamentos superficiais Indufix](https://www.indufix.com.br/pdf/Guia-de-Acabamentos-Superficiais-INDUFIX.pdf), índice e seções de proteção: nomes dos metais/processos, fosfatização, galvanização a fogo, oxidação negra e eletropolimento. |
| forgepdm-options | Registro existente `clients/freecad/freecad/forgepdm/standard_options.py` e suas [fontes de materiais/acabamentos](fastener-options.md). Define os valores aceitos, inclusive opções estendidas. Tradução literal dos constituintes técnicos, preservando códigos e qualificadores; não implica disponibilidade em catálogo brasileiro ou conformidade. |
| forgepdm-editorial | Mensagens de ausência de dados e “não aplicável”, elaboradas para as propostas locais. |

## Escolhas de família

A tabela registra também adaptações editoriais onde uma tradução literal do
Workbench seria estreita demais para todas as normas da mesma família.

| Família canônica | pt-BR | Referência / limite |
| --- | --- | --- |
| HEX HEAD | cabeça sextavada | Fasteners, Indufix |
| HEX FLANGE HEAD | cabeça sextavada com flange | Fasteners; não infere serrilha |
| SOCKET HEAD | cabeça cilíndrica com encaixe interno | Fasteners diferencia acionamento hexalobular; não atribuir sextavado interno a ISO14579 |
| BUTTON HEAD | cabeça abaulada | Fasteners, Indufix; não generalizar flange de ISO7380-2 para ISO7380-1 |
| COUNTERSUNK HEAD | cabeça escareada | Fasteners; alternativa comercial: cabeça chata |
| PAN HEAD | cabeça panela | Fasteners, Indufix |
| CHEESE HEAD | cabeça cilíndrica | Indufix, DIN84; não acrescentar fenda à família que inclui ISO14580 |
| RAISED COUNTERSUNK HEAD | cabeça oval escareada | Fasteners e nomes de cabeças Indufix; distingue da cabeça panela |
| SET | sem cabeça | Indufix; não acrescentar ponta plana/cônica/côncava ou sextavado a todas as normas |
| SHOULDER | com ombro | Adaptação do ressalto/corpo do parafuso ISO7379 descrito por Fasteners e Indufix; não infere acabamento retificado pela família |
| HEX | sextavada | Fasteners, Ciser |
| HEX HIGH | sextavada alta | Fasteners diferencia estilos; altura não é classe de resistência |
| HEX THIN | sextavada baixa | Fasteners, Indufix DIN439 |
| HEX FLANGE | sextavada com flange | Fasteners; sem inferência de serrilha |
| HEX LOCK | sextavada autotravante | Fasteners, Ciser; família abrange também DIN980/ISO7042, sem inferência de nylon |
| CAP | calota | Fasteners, Fusopar |
| SQUARE | quadrada | Fasteners, Fusopar |
| WING | borboleta | Indufix DIN315, Fusopar |
| FLAT | lisa | Indufix, Fusopar |
| SPRING | elástica | Termo amplo editorial para DIN127/128/137; não generalizar geometria helicoidal para arruela ondulada |
| TOOTHED | dentada | Fusopar; não presume dentes internos/externos |
| BELLEVILLE | cônica elástica | Indufix DIN6796; não confundir com dimensões/requisitos de outras molas prato |
| FULL THREAD | com rosca total | Fusopar, registro de opções ForgePDM |

## Materiais, acabamentos e descritores

O recurso cobre os 62 materiais e 37 acabamentos não nulos do registro atual,
mais o termo legado `aluminium`. Aços, inox, ligas de cobre, alumínio e titânio
recebem nomes em português; todos os códigos de liga/têmpera são mantidos.
Monel, Inconel, Hastelloy, Nimonic e as dez siglas de polímeros permanecem
identificadores explícitos. Não se traduz PA6/PA66 para “nylon” de toda a peça.

Acabamentos traduzem somente o processo informado. Zincado genérico não vira
zincado branco; passivação amarela não vira automaticamente bicromatização;
`blackened stainless` não vira automaticamente oxidação negra. Revestimentos
com vários metais conservam todos os constituintes. Óleo, cera, PTFE e camada
orgânica são preservados como qualificadores distintos.

`Blind=true` emite “CEGO” e `LeftHanded=true`, “ROSCA À ESQUERDA”. Os valores
falsos não acrescentam descritores. Valor booleano não reconhecido permanece
visível com aviso. `not applicable` vira “NÃO APLICÁVEL”; classes mecânicas,
como 8.8, 45H, A2-70 e ASTM A193 B7, conservam seus identificadores.

## Lacunas da descrição completa

- Normas fora do mapa, inclusive famílias de cadastro sem norma mapeada: geração
  recusada com orientação para tradução manual. Não adicionar uma norma ao mapa
  apenas porque seu nome parece semelhante.
  Inclui pinos, rebites, insertos, prisioneiros, porcas de canal T/insertos,
  arruelas de contato e classificações `OTHER` do cadastro.
- Material/acabamento livre ou futuro ausente no recurso, incluindo marcas de
  revestimento: conservar o texto recebido e gravar aviso com grupo e valor na
  proveniência do rascunho. Nenhum valor não nulo do registro atual ficou pendente.
  O acabamento legado livre `zinc`, encontrado em fixtures antigas, permanece
  como recebido: identifica o metal, mas não permite escolher com segurança
  entre zincagem eletrolítica, mecânica, a fogo ou lamelar.
- Material, classe ou acabamento nulo: “NÃO ESPECIFICADO” e aviso do campo;
  não inferir aço, classe, revestimento ausente ou “não aplicável”. Diâmetro
  ausente e dimensões customizadas incompletas também geram aviso.
- O mapa é de famílias. Inserto de nylon/não metálico, tipo de ponta, flange
  de subtipos abaulados, serrilha, tipo de acionamento, altura reduzida,
  chanfros e geometria de mola não são detalhados automaticamente. Exigem
  regra específica por norma/dados ou revisão manual; ausência de aviso não
  certifica uma descrição exaustiva ou conformidade normativa.
- Norma, diâmetro, passo, comprimento e classe seguem a normalização vigente da
  especificação. Rótulos dimensionais `W/SL/SW/OD/K/T` continuam identificadores
  técnicos compartilhados. Não são palavras pendentes de tradução.

A [evidência de cobertura](../../validation/fastener-pt-BR-2026-11-18.json)
separa cobertura lexical de tipo/família da completude descritiva acima.
