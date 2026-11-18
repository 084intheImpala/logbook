"""Importing samples from JSON files (samples/import.html, backend/sample_import.py), and samples owned by a team."""
PT = {
    "Download a CLAUDE.md": "Descarregar um CLAUDE.md",
    "for an AI assistant (such as Claude Code) to help prepare the files: put it in the folder with your old records. It explains the format and lists this logbook's step and analysis types, parameters and substrates.":
        "para um assistente de IA (como o Claude Code) ajudar a preparar os ficheiros: ponha-o na pasta com os registos antigos. Explica o formato e lista os tipos de passos e análises, os parâmetros e os substratos deste logbook.",
    # The page
    "Import": "Importar",
    "Import samples": "Importar amostras",
    "Add samples written up in JSON files, such as old samples: one .json file, or a .zip with .json files and the photos and files they name. Everything is checked first and nothing is saved until you confirm.":
        "Acrescente amostras descritas em ficheiros JSON, como amostras antigas: um ficheiro .json, ou um .zip com ficheiros .json e as fotografias e ficheiros que indicam. Tudo é verificado primeiro e nada é guardado até confirmar.",
    "Check": "Verificar",
    "Uploading": "A enviar",
    "Upload done; checking the files. A big zip can take a few minutes.":
        "Envio concluído; a verificar os ficheiros. Um zip grande pode demorar alguns minutos.",
    "Importing: saving the samples and their files. A big zip can take a few minutes.":
        "A importar: a guardar as amostras e os seus ficheiros. Um zip grande pode demorar alguns minutos.",
    "The upload failed. Check the connection and try again.":
        "O envio falhou. Verifique a ligação e tente outra vez.",
    "The server stopped answering. The file may be too big for it: try smaller zips (for example one sample per zip).":
        "O servidor deixou de responder. O ficheiro pode ser grande demais: experimente zips mais pequenos (por exemplo, uma amostra por zip).",
    "Choose a .json or .zip file.": "Escolha um ficheiro .json ou .zip.",
    "That upload has expired or was already imported; upload the file again.":
        "Esse envio expirou ou já foi importado; envie o ficheiro outra vez.",
    "Import complete!": "Importação concluída!",
    "Import more samples": "Importar mais amostras",
    "Upload complete!": "Envio concluído!",
    "Nothing is saved yet: check what would be created below, then click Import.":
        "Ainda nada foi guardado: veja abaixo o que seria criado e carregue em Importar.",
    "Imported 1 sample.": "Importada 1 amostra.",
    "Imported {n} samples.": "Importadas {n} amostras.",
    "Their owners are asked to confirm them; meanwhile you can edit them.":
        "Os donos recebem um pedido para as confirmar; entretanto pode editá-las.",
    "Nothing was imported. Fix these and upload the file again:":
        "Nada foi importado. Corrija isto e envie o ficheiro outra vez:",
    "Worth a look (these don't stop the import):": "A verificar (não impedem a importação):",
    "This would create 1 sample:": "Isto cria 1 amostra:",
    "This would create {n} samples:": "Isto cria {n} amostras:",
    "IDs are given when you import; they may move on if someone adds a sample meanwhile.":
        "Os IDs são atribuídos ao importar; podem avançar se alguém criar uma amostra entretanto.",
    "Entries": "Entradas",
    "asked to confirm": "a aguardar confirmação",
    "Import 1 sample": "Importar 1 amostra",
    "Import {n} samples": "Importar {n} amostras",
    "Samples imported": "Amostras importadas",
    "How to write the file": "Como escrever o ficheiro",
    "A file holds one sample, or a list of them. Types, substrates, projects and procedures are named as they are in the logbook; people by their username. Dates are YYYY-MM-DD; leave out what isn't known.":
        "Um ficheiro tem uma amostra, ou uma lista delas. Tipos, substratos, projetos e procedimentos têm o nome que têm no logbook; as pessoas, o nome de utilizador. As datas são AAAA-MM-DD; deixe de fora o que não se sabe.",
    "Owner: give owner (a username), or team when nobody is known: the sample then belongs to the team and gets its name in the ID. Without either it's yours. Someone else's sample waits for them to confirm it.":
        "Dono: indique owner (um nome de utilizador), ou team quando não se sabe de quem é: a amostra fica da equipa e leva o nome dela no ID. Sem nenhum dos dois, fica sua. A amostra de outra pessoa espera que ela a confirme.",
    "ID year: year, or else the year of the first dated entry, or else this year. Samples are numbered in date order.":
        "Ano do ID: year, ou o ano da primeira entrada com data, ou o ano atual. As amostras são numeradas por ordem de data.",
    "Timeline: steps (kind step), analyses (kind analysis) and cuts (kind cut, with pieces, each with its own timeline), in order.":
        "Cronologia: passos (kind step), análises (kind analysis) e cortes (kind cut, com pieces, cada peça com a sua cronologia), por ordem.",
    "A Deposition can have ref, and a later one on (a ref, or substrate) and partial, for its place in the film stack.":
        "Uma Deposição pode ter ref, e uma posterior on (uma ref, ou substrate) e partial, para o seu lugar no empilhamento de filmes.",
    "Files: paths inside the zip, relative to the .json file.":
        "Ficheiros: caminhos dentro do zip, relativos ao ficheiro .json.",
    "Studies: studies, a list of study titles (studies you co-own); the sample or piece is added to them.":
        "Estudos: studies, uma lista de títulos de estudos (de que seja coautor); a amostra ou peça é acrescentada a eles.",

    # Where a problem is
    "sample {n}": "amostra {n}",
    "entry {n}": "entrada {n}",
    "piece {n}": "peça {n}",

    # Problems with the upload
    "{name}: not valid JSON ({error}).": "{name}: não é JSON válido ({error}).",
    "{name}: not a valid zip file.": "{name}: não é um ficheiro zip válido.",
    "{name}: the zip unpacks to more than 2 GB; split it.": "{name}: o zip descomprimido tem mais de 2 GB; divida-o.",
    "{name}: the zip has no .json file.": "{name}: o zip não tem nenhum ficheiro .json.",
    "expected a sample (an object), a list of samples, or {example}":
        "esperava-se uma amostra (um objeto), uma lista de amostras, ou {example}",
    "a sample must be an object": "uma amostra tem de ser um objeto",
    "an entry must be an object": "uma entrada tem de ser um objeto",
    "a piece must be an object": "uma peça tem de ser um objeto",
    'unknown field "{key}" (allowed: {allowed})': 'campo desconhecido "{key}" (permitidos: {allowed})',
    '"{key}" must be text': '"{key}" tem de ser texto',
    '"{key}" is longer than {n} characters': '"{key}" tem mais de {n} caracteres',
    '"{key}" must be true or false': '"{key}" tem de ser true ou false',
    '"{key}" must be {shape}': '"{key}" tem de ser {shape}',
    '"{key}" should be a number; kept as typed: {value}': '"{key}" devia ser um número; fica como está: {value}',
    '"{key}" should be minutes or min:s; kept as typed: {value}':
        '"{key}" devia ser minutos ou min:s; fica como está: {value}',
    '"{key}" is usually one of {values}': '"{key}" costuma ser um de {values}',
    '"performed_at" must be a date as YYYY-MM-DD, not {value} (leave it out if the day isn\'t known, and say what is known in the notes)':
        '"performed_at" tem de ser uma data AAAA-MM-DD, não {value} (deixe-o de fora se não se sabe o dia, e diga o que se sabe nas notas)',
    '"files" must be a list of file paths': '"files" tem de ser uma lista de caminhos de ficheiros',
    'file "{name}" isn\'t in the zip': 'o ficheiro "{name}" não está no zip',
    '"parameters" must be an object': '"parameters" tem de ser um objeto',
    'parameter "{key}" isn\'t on this type\'s form': 'o parâmetro "{key}" não está no formulário deste tipo',
    'parameter "{key}" isn\'t on this type\'s form: kept as an extra parameter':
        'o parâmetro "{key}" não está no formulário deste tipo: fica como parâmetro extra',
    'give "owner" or "team", not both': 'indique "owner" ou "team", não os dois',
    'no user "{name}" (use their username)': 'não há utilizador "{name}" (use o nome de utilizador)',
    'no team "{name}"': 'não há equipa "{name}"',
    "only members of the {team} team (or an admin) can import its samples":
        "só os membros da equipa {team} (ou um administrador) podem importar amostras dela",
    '"sample_type" must be one of {values}': '"sample_type" tem de ser um de {values}',
    "substrate {name} isn't in the Substrates library (add it there first)":
        "o substrato {name} não está na biblioteca de Substratos (acrescente-o lá primeiro)",
    '"substrate" is needed: a name from the Substrates library':
        'falta "substrate": um nome da biblioteca de Substratos',
    "no project {name} (give its code or name; add it on the Partners tab)":
        "não há projeto {name} (indique o código ou o nome; acrescente-o no separador Parceiros)",
    'a project sample needs "project": its code or name': 'uma amostra de projeto precisa de "project": o código ou o nome',
    'a project sample needs a "description"': 'uma amostra de projeto precisa de "description"',
    '"visibility" must be one of {values}': '"visibility" tem de ser um de {values}',
    '"year" must be a year such as 2021': '"year" tem de ser um ano, como 2021',
    '"is_reference" must be true or false': '"is_reference" tem de ser true ou false',
    "{name} hasn't set their initials, so their samples can't get an ID":
        "{name} ainda não definiu as iniciais, por isso as suas amostras não podem ter ID",
    'the team name "{team}" can\'t be used for sample IDs (it needs 2 to 6 letters or digits)':
        'o nome da equipa "{team}" não pode ser usado nos IDs das amostras (precisa de 2 a 6 letras ou algarismos)',
    '"tags" must be a list of words': '"tags" tem de ser uma lista de palavras',
    '"studies" must be a list of study titles': '"studies" tem de ser uma lista de títulos de estudos',
    'no study "{title}" that you co-own (samples can be added only to those)':
        'não há nenhum estudo "{title}" de que seja coautor (só se podem acrescentar amostras a esses)',
    'several of your studies are called "{title}"; rename one first':
        'vários dos seus estudos chamam-se "{title}"; mude primeiro o nome a um deles',
    '"timeline" must be a list': '"timeline" tem de ser uma lista',
    '"kind" must be "step", "analysis" or "cut"': '"kind" tem de ser "step", "analysis" ou "cut"',
    'no process step type "{name}"': 'não há tipo de passo "{name}"',
    'no analysis type "{name}"': 'não há tipo de análise "{name}"',
    "a cut is written as {example}": "um corte escreve-se {example}",
    '"{type}" can\'t be imported; add the devices on the sample page':
        '"{type}" não pode ser importado; acrescente os dispositivos na página da amostra',
    'no procedure "{title}" that you can see': 'não há nenhum procedimento "{title}" que possa ver',
    'more than one procedure is called "{title}"': 'há mais de um procedimento chamado "{title}"',
    '"on" and "partial" are only for a Deposition': '"on" e "partial" são só para uma Deposição',
    '"on": no earlier Deposition with "ref": {ref} (or use "substrate")':
        '"on": não há uma Deposição anterior com "ref": {ref} (ou use "substrate")',
    '"on": {ref} isn\'t a Deposition': '"on": {ref} não é uma Deposição',
    '"partial" must be true or false': '"partial" tem de ser true ou false',
    '"ref" must be a name': '"ref" tem de ser um nome',
    '"ref" {ref} is used twice': '"ref" {ref} aparece duas vezes',
    '"run" must be a name': '"run" tem de ser um nome',
    '"run" {run} joins entries of different types': '"run" {run} junta entradas de tipos diferentes',
    'a cut needs "pieces": a list with one object per piece': 'um corte precisa de "pieces": uma lista com um objeto por peça',
    "a cut can keep at most one reference piece": "um corte só pode guardar uma peça de referência",

    # Samples owned by a team
    "The {team} team": "A equipa {team}",
    "This sample belongs to the {team} team: its members can edit it and give it to a researcher (Edit → Researcher).":
        "Esta amostra é da equipa {team}: os membros podem editá-la e entregá-la a um investigador (Editar → Investigador(a)).",
}
