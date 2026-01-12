import discord
from discord.ext import commands
import random
import sqlite3
import re

# ----------------------------
# Configurações e Inicialização
# ----------------------------
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

DB_FILE = 'rpg_fichas.db'
SANIDADE_GIF = "https://imgs.search.brave.com/BHFZ571hFMLk0s8FLwiInUFie0DMUh8K6HpiOv_PdKs/rs:fit:860:0:0:0/g:ce/aHR0cHM6Ly9tZWRp/YTEuZ2lwaHkuY29t/L21lZGlhL3hVTmQ5/R1J6cjJvREZ1eXVX/Yy8yMDAuZ2lmP2Np/ZD03OTBiNzYxMWg4/cWR5a2F2Y3R6OTIy/djc5cXg4cmpqa2J1/M3FycG9jNXkwMHlv/NG8mZXA9djFfZ2lm/c19zZWFyY2gmcmlk/PTIwMC5naWYmY3Q9/Zw.gif"

# ----------------------------
# Banco de Dados
# ----------------------------
def iniciar_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Tabela fichas (com colunas novas já previstas)
    cursor.execute('''CREATE TABLE IF NOT EXISTS fichas (
        user_id TEXT, nome TEXT, foto_url TEXT,
        forca INTEGER, velocidade INTEGER, esquiva INTEGER, constituicao INTEGER,
        atordoamento INTEGER, peste INTEGER, doencas INTEGER, sangramento INTEGER, debuff INTEGER,
        nivel INTEGER DEFAULT 1, xp INTEGER DEFAULT 0,
        pontos_atrib INTEGER DEFAULT 0, pontos_res INTEGER DEFAULT 0,
        espaco_bolsa INTEGER DEFAULT 6,
        saldo INTEGER DEFAULT 0,
        estresse INTEGER DEFAULT 0,
        vida INTEGER DEFAULT 0,
        arma_equipada TEXT DEFAULT NULL,
        armadura_equipada TEXT DEFAULT NULL,
        UNIQUE(user_id, nome))''')

    # Inventário
    cursor.execute('''CREATE TABLE IF NOT EXISTS inventario (
        user_id TEXT, nome_personagem TEXT, 
        item_nome TEXT, quantidade INTEGER,
        PRIMARY KEY (user_id, nome_personagem, item_nome))''')

    # Skills (inclui coluna tipo para distinguir dano/curas)
    cursor.execute('''CREATE TABLE IF NOT EXISTS skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT, nome_personagem TEXT, nome_skill TEXT, dano_formula TEXT, descricao TEXT,
        tipo TEXT DEFAULT 'dano')''')

    # Ativo
    cursor.execute('''CREATE TABLE IF NOT EXISTS ativo (
        user_id TEXT PRIMARY KEY, nome_personagem TEXT)''')

    # Armas
    cursor.execute('''CREATE TABLE IF NOT EXISTS armas (
        user_id TEXT, nome_personagem TEXT,
        item_nome TEXT, nivel INTEGER, d6 INTEGER,
        PRIMARY KEY (user_id, nome_personagem, item_nome))''')

    # Armaduras
    cursor.execute('''CREATE TABLE IF NOT EXISTS armaduras (
        user_id TEXT, nome_personagem TEXT,
        item_nome TEXT, nivel INTEGER, d6 INTEGER,
        bonus_esquiva INTEGER DEFAULT 0, bonus_velocidade INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, nome_personagem, item_nome))''')

    conn.commit()
    conn.close()

# Garante compatibilidade caso a tabela antiga não tenha colunas adicionadas
def migrar_colunas_opcionais():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    optional_alter = [
        ("fichas", "saldo INTEGER DEFAULT 0"),
        ("fichas", "estresse INTEGER DEFAULT 0"),
        ("fichas", "vida INTEGER DEFAULT 0"),
        ("fichas", "arma_equipada TEXT DEFAULT NULL"),
        ("fichas", "armadura_equipada TEXT DEFAULT NULL"),
        ("skills", "tipo TEXT DEFAULT 'dano'")
    ]
    for table, clause in optional_alter:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {clause}")
            conn.commit()
        except Exception:
            pass
    conn.close()

iniciar_db()
migrar_colunas_opcionais()

# ----------------------------
# Utilitárias
# ----------------------------
def get_ativo(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT nome_personagem FROM ativo WHERE user_id = ?", (str(user_id),))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else None

def rolar_dados(formula):
    """Rola uma fórmula no formato XdY e retorna (lista_de_rolagens, soma) ou (None, None) se inválida."""
    try:
        if not formula:
            return None, None
        match = re.match(r"^\s*(\d+)\s*d\s*(\d+)\s*$", formula.lower())
        if not match:
            return None, None
        qtd, faces = int(match.group(1)), int(match.group(2))
        if qtd <= 0 or faces <= 0:
            return None, None
        rolagens = [random.randint(1, faces) for _ in range(qtd)]
        return rolagens, sum(rolagens)
    except Exception:
        return None, None

async def adicionar_xp_logica(user_id, nome_personagem, quantidade):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT xp, nivel, constituicao, pontos_atrib, pontos_res, vida FROM fichas WHERE user_id = ? AND nome = ?", (str(user_id), nome_personagem))
    res = cursor.fetchone()
    if not res:
        conn.close()
        return None, False
    xp_atual, nivel_atual, const, p_atrib, p_res, vida_atual = res
    if nivel_atual >= 20:
        conn.close()
        return nivel_atual, "max"
    novo_xp = xp_atual + quantidade
    xp_necessario = 25 + (nivel_atual * 5)
    upou = False
    const_ganho_total = 0
    while novo_xp >= xp_necessario and nivel_atual < 20:
        novo_xp -= xp_necessario
        nivel_atual += 1
        const += 1
        const_ganho_total += 1
        p_atrib += 1
        p_res += 1
        xp_necessario = 25 + (nivel_atual * 5)
        upou = True
    if const_ganho_total > 0:
        vida_atual = (vida_atual or 0) + (5 * const_ganho_total)
    cursor.execute("""UPDATE fichas SET xp = ?, nivel = ?, constituicao = ?, 
                      pontos_atrib = ?, pontos_res = ?, vida = ?
                      WHERE user_id = ? AND nome = ?""",
                   (novo_xp, nivel_atual, const, p_atrib, p_res, vida_atual, str(user_id), nome_personagem))
    conn.commit()
    conn.close()
    return nivel_atual, upou

# ----------------------------
# Economia (conversões e parser)
# ----------------------------
def to_verde(quantidade: int, moeda: str) -> int:
    m = moeda.lower()
    if m in ("v", "verde", "verdes", "rúpia_verde", "rupia_verde", "rupia"):
        return quantidade
    if m in ("a", "azul", "azuis", "rúpia_azul", "rúpiaazul"):
        return quantidade * 1000
    if m in ("r", "vermelha", "vermelhas", "vermelho", "rúpia_vermelha", "rupia_vermelha"):
        return quantidade * 100000
    return None

def formatar_saldo(saldo_verde: int) -> str:
    vermelhas = saldo_verde // 100000
    resto = saldo_verde % 100000
    azuis = resto // 1000
    verdes = resto % 1000
    parts = []
    if vermelhas:
        parts.append(f"**{vermelhas}** 🟥")
    if azuis:
        parts.append(f"**{azuis}** 🟦")
    if verdes or not parts:
        parts.append(f"**{verdes}** 🟩")
    return " | ".join(parts)

CURRENCY_WORDS = {
    'r': ('r', 'vermelha', 'vermelhas', 'vermelho', 'rv', 'red'),
    'a': ('a', 'azul', 'azuis', 'av', 'blue'),
    'v': ('v', 'verde', 'verdes', 'gv', 'green')
}

def identify_short_currency(word: str):
    w = word.lower()
    for short, variants in CURRENCY_WORDS.items():
        if w in variants:
            return short
    return None

def parse_money_tokens(args):
    """
    Recebe tokens como: 1r 5a 200v ou ['500', 'verde'] e retorna total em verdes (int) ou (None, erro_str).
    """
    if not args:
        return None, "❌ Forneça valores. Ex: `!receber 1r 5a 200v` ou `!receber 500 verde`."
    tokens = list(args)
    # Caso formato: !receber 500 verde
    if len(tokens) == 2 and tokens[0].isdigit():
        short = identify_short_currency(tokens[1])
        if short:
            tokens = [tokens[0] + short]
        else:
            return None, "❌ Moeda inválida. Use `verde`, `azul` ou `vermelha`."
    total_verdes = 0
    for t in tokens:
        t = t.lower().strip()
        m = re.match(r'^(\d+)([a-z]+)?$', t)
        if not m:
            return None, f"❌ Token inválido: `{t}`. Use `1r`, `2a`, `500v` ou `500 verde`."
        qty = int(m.group(1))
        cur_part = m.group(2)
        if cur_part is None:
            return None, f"❌ Especifique a moeda para `{t}` (ex.: `500v` ou `500 verde`)."
        if len(cur_part) == 1 and cur_part in ('r','a','v'):
            short = cur_part
        else:
            short = identify_short_currency(cur_part)
            if not short:
                return None, f"❌ Moeda inválida em `{t}`. Use `verde`, `azul` ou `vermelha`."
        converted = to_verde(qty, {'r':'vermelha','a':'azul','v':'verde'}[short])
        if converted is None:
            return None, f"❌ Erro ao converter `{t}`."
        total_verdes += converted
    return total_verdes, None

# ----------------------------
# Comandos de Ajuda organizados
# ----------------------------
@bot.command()
async def helpdados(ctx):
    embed = discord.Embed(title="📖 Manual Rápido do Aventureiro", color=discord.Color.gold())
    embed.description = (
        "Resumo dos comandos principais. Use os comandos abaixo para ver seções detalhadas.\n\n"
        "• `!ficha` — Mostra a sua ficha com as principais informações do personagem.\n"
        "• `!helpcombate` — Regras e comandos de combate, HP e estresse.\n"
        "• `!helpskills` — Como criar, editar, listar, usar e excluir skills.\n"
        "• `!helpcadastro` — Como cadastrar personagem.\n"
        "• `!helpmestre` — Comandos e utilitários do Mestre/DM.\n"
        "• `!helpinventario` — Gerenciar itens e bolsa.\n"
        "• `!receber` / `!gastar` — Sistema monetário e carteira.\n\n"
        "Dica: sempre use `!set [Nome]` ao entrar no servidor para ativar seu personagem."
    )
    embed.set_footer(text="Use aspas se o nome tiver espaços. Comandos entre colchetes [] são parâmetros.")
    await ctx.send(embed=embed)

@bot.command()
async def helpcadastro(ctx):
    """Guia de cadastro e comandos relacionados a equipamentos"""
    embed = discord.Embed(title="📝 Guia de Cadastro de Ficha", color=discord.Color.blue())
    embed.description = "Siga a ordem exata para o bot registrar seus atributos corretamente. Use aspas se o nome tiver espaços."
    embed.add_field(
        name="📋 Comando de cadastro",
        value="`!cadastrar \"Nome\" LinkDaFoto Nivel FRC VEL ESQ CST ATD PST DOE SAN DBF`",
        inline=False
    )
    embed.add_field(
        name="💡 Exemplo de cadastro",
        value="`!cadastrar \"Kael\" http://foto.com/kael.png 5 10 12 15 10 0 0 0 0 5`",
        inline=False
    )
    embed.add_field(
        name="⚔️ Como adicionar armas",
        value=(
            "• `!adicionar arma \"Nome da Arma\" Nivel D6`\n"
            "  • **Nome:** use aspas se tiver espaços.\n"
            "  • **Nivel:** inteiro (ex.: 1, 2, 3).\n"
            "  • **D6:** número de d6 que a arma usa para ataque (ex.: `2` para `2d6`).\n"
            "  • **Exemplo:** `!adicionar arma \"Espada Longa\" 2 2` — cadastra e equipa uma arma Nível 2 que causa 2d6 de ataque."
        ),
        inline=False
    )
    embed.add_field(
        name="🛡️ Como adicionar armaduras",
        value=(
            "• `!adicionar armadura \"Nome da Armadura\" Nivel D6 [bonus_esq] [bonus_vel]`\n"
            "  • **Nivel:** inteiro.\n"
            "  • **D6:** número de d6 que a armadura usa para defesa (ex.: `1` para `1d6`).\n"
            "  • **bonus_esq / bonus_vel:** opcionais; inteiros que somam em Esquiva e Velocidade do personagem.\n"
            "  • **Exemplo:** `!adicionar armadura \"Couraça\" 1 1 2 0` — cadastra e equipa uma armadura Nível 1 (1d6 defesa) que dá +2 Esquiva."
        ),
        inline=False
    )
    embed.add_field(
        name="🗑️ Como remover arma ou armadura",
        value=(
            "• `!remover arma \"Nome da Arma\"` — remove a arma do banco de dados do personagem (use aspas se necessário).\n"
            "• `!remover armadura \"Nome da Armadura\"` — remove a armadura do banco de dados do personagem.\n"
            "  • **Exemplo:** `!remover arma \"Espada Longa\"`"
        ),
        inline=False
    )
    embed.add_field(
        name="⬆️ Como upar arma e armadura (sem remover)",
        value=(
            "• `!upararma \"Nome da Arma\" nivel_inc d6_inc` — incrementa nível e d6 da arma (pode ser negativo).\n"
            "  • **Exemplo:** `!upararma \"Espada Longa\" 1 1` — aumenta nível em 1 e d6 em 1.\n"
            "• `!upararmadura \"Nome da Armadura\" nivel_inc d6_inc bonus_esq_inc bonus_vel_inc` — atualiza armadura existente.\n"
            "  • **Exemplo:** `!upararmadura \"Couraça\" 1 0 2 0` — +1 nível, +0 d6, +2 Esquiva."
        ),
        inline=False
    )
    embed.add_field(
        name="🔎 Dicas importantes",
        value=(
            "• Use `!set [Nome]` após cadastrar para ativar o personagem.\n"
            "• `!ficha` mostra Vida, Estresse, Equipamento e Carteira.\n"
            "• Atualizar (`upararma` / `upararmadura`) preserva histórico e evita recriar itens.\n"
            "• Remoções e upgrades podem exigir permissão de Mestre/ADM dependendo da implementação."
        ),
        inline=False
    )
    embed.set_footer(text="Qualquer dúvida sobre o formato, consulte o mestre ou use !helpdados para ver outras seções.")
    await ctx.send(embed=embed)


@bot.command()
async def helpinventario(ctx):
    """Ajuda sobre comandos de inventário e gerenciamento de bolsa"""
    embed = discord.Embed(title="🎒 Ajuda — Inventário", color=discord.Color.dark_green())
    embed.description = "Comandos para gerenciar itens, espaço da bolsa e uso de consumíveis."
    embed.add_field(
        name="Visualizar",
        value=(
            "• `!inv` ou `!inventario` — Mostra os itens do personagem ativo e o espaço ocupado.\n"
            "• Exemplo: `!inv`"
        ),
        inline=False
    )
    embed.add_field(
        name="Adicionar / Guardar",
        value=(
            "• `!inv adicionar [item] [qtd]` — Adiciona um item à bolsa (respeita o limite de espaço).\n"
            "• Exemplo: `!inv adicionar Poção 2`"
        ),
        inline=False
    )
    embed.add_field(
        name="Usar / Consumir",
        value=(
            "• `!usar [item] [qtd]` — Usa/consome um item do inventário (reduz quantidade).\n"
            "• Exemplo: `!usar Poção 1`"
        ),
        inline=False
    )
    embed.add_field(
        name="Observações úteis",
        value=(
            "• Itens com o mesmo nome se acumulam (mesmo nome, mesma entrada).\n"
            "• Use nomes simples ou sem acentos para evitar problemas; o bot armazena itens em minúsculas.\n"
            "• Se a bolsa estiver cheia, `!inv adicionar` retornará erro informando falta de espaço."
        ),
        inline=False
    )
    embed.set_footer(text="Dica: use `!ficha` para ver o espaço total da bolsa do personagem ativo.")
    await ctx.send(embed=embed)

@bot.command()
async def helpcombate(ctx):
    """Ajuda detalhada sobre combate, HP, estresse e comandos relacionados"""
    embed = discord.Embed(title="⚔️ Ajuda — Combate e Estado", color=discord.Color.red())
    embed.add_field(
        name="Vida (HP)",
        value=(
            "• **HP máximo = Constituição × 5**.\n"
            "• `!ferimento [valor]` — causa dano ao personagem ativo (reduz HP atual).\n"
            "• `!curou [valor]` — cura HP do personagem ativo (não ultrapassa o máximo).\n"
            "• `!ficha` mostra Vida atual e HP máximo."
        ),
        inline=False
    )
    embed.add_field(
        name="Estresse / Sanidade",
        value=(
            "• `!estressou [valor]` — aumenta Estresse (0 → 200).\n"
            "• `!desestressou [valor]` — reduz Estresse (mín 0).\n"
            "• Ao atingir **200**: o bot envia mensagem de sanidade e GIF automático."
        ),
        inline=False
    )
    embed.add_field(
        name="Skills de Cura",
        value=(
            "• `!addskill \"Nome\" XdY cura [Descrição]` — cadastra skill do tipo cura (ex.: `2d6`).\n"
            "• `!skill \"Nome da Skill\" @Jogador` — executa a skill; se for cura, aplica no personagem ativo do jogador mencionado.\n"
            "• Se omitir o alvo, `!skill` aplica no personagem ativo do autor."
        ),
        inline=False
    )
    embed.set_footer(text="Use estes comandos durante a sessão para controlar vida e sanidade dos personagens.")
    await ctx.send(embed=embed)
@bot.command()
async def helpmestre(ctx):
    """Painel de comandos do Mestre / Administrador"""
    embed = discord.Embed(title="🧙 Painel do Mestre (ADM)", color=discord.Color.red())
    embed.description = "Comandos reservados para Mestres/Administradores. Use com responsabilidade."
    embed.add_field(
        name="🎯 Distribuição de XP",
        value=(
            "• `!darxp @Jogador [valor]` — Dá XP ao personagem ativo do jogador mencionado.\n"
            "• `!darxpmulti [valor] @Jog1 @Jog2 ...` — Dá XP para vários mencionados de uma vez."
        ),
        inline=False
    )
    embed.add_field(
        name="🎒 Inventário / Bolsa",
        value=(
            "• `!inv expandir @membro [qtd]` — Aumenta o espaço da bolsa do personagem ativo do membro."
        ),
        inline=False
    )
    embed.add_field(
        name="⚠️ Permissões",
        value=(
            "Estes comandos exigem permissão de Administrador no servidor. Se você não for ADM, verá uma mensagem de permissão."
        ),
        inline=False
    )
    embed.set_footer(text="Use estes comandos para gerenciar sessões, recompensas e recursos dos jogadores.")
    await ctx.send(embed=embed)

@bot.command()
async def helpskills(ctx):
    """Ajuda detalhada sobre criação, edição, listagem e remoção de skills"""
    embed = discord.Embed(title="🛠️ Ajuda — Skills", color=discord.Color.blue())
    embed.add_field(
        name="Cadastrar Skill",
        value=(
            "• `!addskill \"Nome\" XdY [tipo] [Descrição]`: Cadastra uma skill nova.\n"
            "  • **Nome:** use aspas se tiver espaços.\n"
            "  • **XdY:** fórmula (ex.: `2d6`).\n"
            "  • **tipo:** `dano` (padrão) ou `cura` (ex.: `!addskill \"Cura Leve\" 2d6 cura Resta`)."
        ),
        inline=False
    )
    embed.add_field(
        name="Editar Skill",
        value=(
            "• `!editskill NomeDaSkill dano 3d6` — altera fórmula de dano/curar.\n"
            "• `!editskill NomeDaSkill desc Nova descrição` — altera descrição.\n"
            "• `!editskill NomeDaSkill tipo cura` — altera tipo (dano/cura)."
        ),
        inline=False
    )
    embed.add_field(
        name="Listar e Ver detalhes",
        value=(
            "• `!skills [filtro]` — lista todas as skills (ou filtra por texto no nome/descrição).\n"
            "• `!skillinfo NomeDaSkill` — mostra descrição completa, fórmula e rolagem de exemplo."
        ),
        inline=False
    )
    embed.add_field(
        name="Executar e Remover",
        value=(
            "• `!skill \"Nome da Skill\" @Jogador` — executa a skill (cura aplica automaticamente no alvo).\n"
            "• `!removeskill \"Nome da Skill\"` — remove a skill do personagem ativo."
        ),
        inline=False
    )
    embed.set_footer(text="Exemplos: `!addskill \"Granada\" 2d6 dano Explode` | `!removeskill \"Granada\"`")
    await ctx.send(embed=embed)

# ----------------------------
# Inventário (inv, inv adicionar, inv expandir, usar)
# ----------------------------
@bot.group(name="inventario", invoke_without_command=True, aliases=["inv", "Inventário"])
async def inventario(ctx):
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use !set primeiro.")
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("SELECT espaco_bolsa FROM fichas WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
    limite = cursor.fetchone()[0]
    cursor.execute("SELECT item_nome, quantidade FROM inventario WHERE user_id = ? AND nome_personagem = ?", (str(ctx.author.id), ativo))
    itens = cursor.fetchall()
    conn.close()
    embed = discord.Embed(title=f"🎒 Inventário de {ativo}", color=discord.Color.dark_green())
    slots_ocupados = len(itens)
    if not itens:
        embed.description = "Sua bolsa está vazia."
    else:
        lista = "\n".join([f"• **{item[0]}** x{item[1]}" for item in itens])
        embed.description = lista
    embed.set_footer(text=f"Espaço: {slots_ocupados}/{limite}")
    await ctx.send(embed=embed)

@inventario.command(name="adicionar")
async def inv_add(ctx, item: str, quantidade: int = 1):
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use !set primeiro.")
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("SELECT espaco_bolsa FROM fichas WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
    limite = cursor.fetchone()[0]
    cursor.execute("SELECT item_nome FROM inventario WHERE user_id = ? AND nome_personagem = ?", (str(ctx.author.id), ativo))
    itens_atuais = [row[0] for row in cursor.fetchall()]
    if item.lower() not in [i.lower() for i in itens_atuais] and len(itens_atuais) >= limite:
        conn.close()
        return await ctx.send("Oh-oh... Não tem espaço na bolsa para isso.")
    cursor.execute('''INSERT INTO inventario (user_id, nome_personagem, item_nome, quantidade)
                      VALUES (?, ?, ?, ?)
                      ON CONFLICT(user_id, nome_personagem, item_nome) 
                      DO UPDATE SET quantidade = quantidade + ?''',
                   (str(ctx.author.id), ativo, item.lower(), quantidade, quantidade))
    conn.commit(); conn.close()
    await ctx.send(f"📦 **{quantidade}x {item}** adicionado ao inventário de **{ativo}**!")

@inventario.command(name="expandir")
@commands.has_permissions(administrator=True)
async def inv_expandir(ctx, membro: discord.Member, quantidade: int = 1):
    ativo = get_ativo(membro.id)
    if not ativo:
        return await ctx.send(f"❌ {membro.display_name} não tem um personagem ativo no momento.")
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("UPDATE fichas SET espaco_bolsa = espaco_bolsa + ? WHERE user_id = ? AND nome = ?", (quantidade, str(membro.id), ativo))
    cursor.execute("SELECT espaco_bolsa FROM fichas WHERE user_id = ? AND nome = ?", (str(membro.id), ativo))
    novo_limite = cursor.fetchone()[0]
    conn.commit(); conn.close()
    await ctx.send(f"🎒 A bolsa de **{ativo}** (Personagem de {membro.mention}) foi expandida em +{quantidade}!\nTotal atual: **{novo_limite}** slots.")

@bot.command(name="usar")
async def usar_item(ctx, item: str, quantidade: int = 1):
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use !set primeiro.")
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("SELECT quantidade FROM inventario WHERE user_id = ? AND nome_personagem = ? AND item_nome = ?", (str(ctx.author.id), ativo, item.lower()))
    res = cursor.fetchone()
    if not res or res[0] < quantidade:
        conn.close()
        return await ctx.send(f"❌ Você não tem {quantidade}x {item} para usar.")
    nova_qtd = res[0] - quantidade
    if nova_qtd <= 0:
        cursor.execute("DELETE FROM inventario WHERE user_id = ? AND nome_personagem = ? AND item_nome = ?", (str(ctx.author.id), ativo, item.lower()))
    else:
        cursor.execute("UPDATE inventario SET quantidade = ? WHERE user_id = ? AND nome_personagem = ? AND item_nome = ?", (nova_qtd, str(ctx.author.id), ativo, item.lower()))
    conn.commit(); conn.close()
    await ctx.send(f"✨ **{ativo}** usou {quantidade}x **{item}**!")

# ----------------------------
# Fichas, XP e Atributos
# ----------------------------
@bot.command()
async def upar(ctx, tipo: str, *, atributo: str):
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use !set primeiro.")
    mapa_atrib = {"forca": "forca", "vel": "velocidade", "esq": "esquiva", "const": "constituicao"}
    mapa_res = {"atord": "atordoamento", "peste": "peste", "doenca": "doencas", "sangra": "sangramento", "debuff": "debuff"}
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("SELECT pontos_atrib, pontos_res, constituicao, vida FROM fichas WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
    pontos = cursor.fetchone()
    atr = atributo.lower().strip()
    msg = ""
    if tipo.lower() == "atributo":
        if atr not in mapa_atrib:
            conn.close()
            return await ctx.send(f"❌ Escolha entre: {', '.join(mapa_atrib.keys())}")
        if pontos[0] <= 0:
            conn.close()
            return await ctx.send("❌ Você não tem pontos de atributo para gastar.")
        if atr == "const":
            cursor.execute(f"UPDATE fichas SET {mapa_atrib[atr]} = {mapa_atrib[atr]} + 1, pontos_atrib = pontos_atrib - 1, vida = vida + 5 WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
        else:
            cursor.execute(f"UPDATE fichas SET {mapa_atrib[atr]} = {mapa_atrib[atr]} + 1, pontos_atrib = pontos_atrib - 1 WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
        msg = f"✅ +1 em **{atr.capitalize()}**! (Pontos restantes: {pontos[0]-1})"
    elif tipo.lower() in ["res", "resistencia"]:
        if atr not in mapa_res:
            conn.close()
            return await ctx.send(f"❌ Escolha entre: {', '.join(mapa_res.keys())}")
        if pontos[1] <= 0:
            conn.close()
            return await ctx.send("❌ Você não tem pontos de resistência para gastar.")
        cursor.execute(f"UPDATE fichas SET {mapa_res[atr]} = {mapa_res[atr]} + 1, pontos_res = pontos_res - 1 WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
        msg = f"✅ +1 em **Resistência a {atr.capitalize()}**! (Pontos restantes: {pontos[1]-1})"
    else:
        conn.close()
        return await ctx.send("❌ Use `!upar atributo [nome]` ou `!upar res [nome]`.")
    conn.commit(); conn.close()
    await ctx.send(f"✨ **{ativo}** evoluiu! {msg}")

@bot.command()
async def cadastrar(ctx, nome: str, foto_url: str, nivel: int = 1, *status: int):
    stats = list(status)
    while len(stats) < 9:
        stats.append(0)
    stats = stats[:9]
    constituicao = stats[3]
    vida_inicial = constituicao * 5
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute('''INSERT OR REPLACE INTO fichas 
            (user_id, nome, foto_url, forca, velocidade, esquiva, constituicao, 
            atordoamento, peste, doencas, sangramento, debuff, nivel, xp, 
            pontos_atrib, pontos_res, espaco_bolsa, saldo, estresse, vida, arma_equipada, armadura_equipada) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (str(ctx.author.id), nome.strip(), foto_url.strip(), *stats, nivel, 0, 0, 0, 6, 0, 0, vida_inicial, None, None))
        conn.commit()
        cursor.execute("INSERT OR REPLACE INTO ativo (user_id, nome_personagem) VALUES (?, ?)", (str(ctx.author.id), nome.strip()))
        conn.commit()
        await ctx.send(f"✅ Ficha de **{nome}** salva no nível **{nivel}** e pronta pra aventura! (Vida: {vida_inicial})")
    except Exception as e:
        await ctx.send(f"❌ Erro ao cadastrar: {e}")
    finally:
        conn.close()

@bot.command()
async def ficha(ctx):
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Você não tem um personagem ativo. Use `!set [nome]` ou `!cadastrar`.")
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("""SELECT nome, foto_url, forca, velocidade, esquiva, constituicao,
                      atordoamento, peste, doencas, sangramento, debuff,
                      nivel, xp, pontos_atrib, pontos_res, espaco_bolsa, saldo, estresse, vida, arma_equipada, armadura_equipada
                      FROM fichas WHERE user_id = ? AND nome = ?""", (str(ctx.author.id), ativo))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return await ctx.send(f"❌ Erro: Não encontrei os dados da ficha de **{ativo}**.")
    (nome, foto_url, forca, velocidade, esquiva, constituicao,
     atordoamento, peste, doencas, sangramento, debuff,
     nivel, xp, pontos_atrib, pontos_res, espaco_bolsa, saldo, estresse, vida_atual, arma_equipada, armadura_equipada) = row
    conn.close()
    max_hp = (constituicao or 0) * 5
    vida_atual = min(vida_atual or max_hp, max_hp)
    prox_xp = 25 + (nivel * 5)

    emb = discord.Embed(title=f"📜 {nome} | Nível {nivel}", color=0x7289da)
    emb.add_field(name="❤️ Vida", value=f"**{vida_atual}/{max_hp}**", inline=True)
    emb.add_field(name="😰 Estresse", value=f"**{estresse}/200**", inline=True)
    emb.add_field(name="📊 Experiência", value=f"`{xp:02d}/{prox_xp:02d}`", inline=False)

    if pontos_atrib > 0 or pontos_res > 0:
        emb.add_field(name="✨ Pontos Disponíveis", value=f"Atributos: **{pontos_atrib}** | Resistências: **{pontos_res}**\nUse `!upar` para gastar!", inline=False)

    # Atributos principais (organizados)
    emb.add_field(name="⚔️ Força", value=f"**{forca}**", inline=True)
    emb.add_field(name="⚡ Vel", value=f"**{velocidade}**", inline=True)
    emb.add_field(name="🛡️ Esq", value=f"**{esquiva}**", inline=True)
    emb.add_field(name="❤️ Const", value=f"**{constituicao}**", inline=True)

    # Resistências e condições
    emb.add_field(name="🌀 Atordoamento", value=f"**{atordoamento}**", inline=True)
    emb.add_field(name="🤢 Peste", value=f"**{peste}**", inline=True)
    emb.add_field(name="🤒 Doença", value=f"**{doencas}**", inline=True)
    emb.add_field(name="🩸 Sangramento", value=f"**{sangramento}**", inline=True)
    emb.add_field(name="📉 Debuff", value=f"**{debuff}**", inline=True)

    # Equipamento
    equip_text = []
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    if arma_equipada:
        cursor.execute("SELECT nivel, d6 FROM armas WHERE user_id = ? AND nome_personagem = ? AND item_nome = ?", (str(ctx.author.id), ativo, arma_equipada))
        arow = cursor.fetchone()
        if arow:
            equip_text.append(f"**Arma:** {arma_equipada} (Nível {arow[0]} | {arow[1]}d6 ataque)")
        else:
            equip_text.append(f"**Arma:** {arma_equipada} (não encontrada nos registros)")
    else:
        equip_text.append("**Arma:** Nenhuma")
    if armadura_equipada:
        cursor.execute("SELECT nivel, d6, bonus_esquiva, bonus_velocidade FROM armaduras WHERE user_id = ? AND nome_personagem = ? AND item_nome = ?", (str(ctx.author.id), ativo, armadura_equipada))
        arow = cursor.fetchone()
        if arow:
            btext = []
            if arow[2]:
                btext.append(f"+{arow[2]} Esquiva")
            if arow[3]:
                btext.append(f"+{arow[3]} Vel")
            bonus_str = " | ".join(btext) if btext else "Sem bônus"
            equip_text.append(f"**Armadura:** {armadura_equipada} (Nível {arow[0]} | {arow[1]}d6 defesa; {bonus_str})")
        else:
            equip_text.append(f"**Armadura:** {armadura_equipada} (não encontrada nos registros)")
    else:
        equip_text.append("**Armadura:** Nenhuma")
    conn.close()

    emb.add_field(name="🧰 Equipamento", value="\n".join(equip_text), inline=False)
    emb.add_field(name="💰 Carteira", value=f"{formatar_saldo(saldo or 0)}", inline=False)
    if str(foto_url).startswith("http"):
        emb.set_image(url=foto_url)
    emb.set_footer(text=f"Espaço na bolsa: {espaco_bolsa}")
    await ctx.send(embed=emb)

# ----------------------------
# XP / Mestre
# ----------------------------
@bot.command()
async def ganharxp(ctx, quantidade: int):
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use `!set` primeiro.")
    nv, res = await adicionar_xp_logica(ctx.author.id, ativo, quantidade)
    if res == "max":
        await ctx.send(f"🏆 {ativo} já está no nível máximo!")
    elif res:
        await ctx.send(f"🎊 **LEVEL UP!** {ativo} subiu para o nível **{nv}**! (Constituição aumentada e vida ajustada)")
    else:
        await ctx.send(f"✨ {ativo} ganhou {quantidade} de XP.")

@bot.command()
@commands.has_permissions(administrator=True)
async def darxp(ctx, membro: discord.Member, quantidade: int):
    ativo = get_ativo(membro.id)
    if not ativo:
        return await ctx.send(f"❌ {membro.display_name} não tem personagem ativo.")
    nv, res = await adicionar_xp_logica(membro.id, ativo, quantidade)
    if res == "max":
        await ctx.send(f"🏆 {ativo} está no máximo.")
    elif res:
        await ctx.send(f"🎊 **LEVEL UP!** {membro.mention}, **{ativo}** subiu para o nível **{nv}**! (Constituição aumentada e vida ajustada)")
    else:
        await ctx.send(f"✨ **{membro.display_name}** recebeu {quantidade} de XP em **{ativo}**.")

@bot.command(name="darxpmulti")
async def darxp_multi(ctx, quantidade: int, *membros: discord.Member):
    """
    Dá XP para múltiplos jogadores mencionados.
    Uso: !darxpmulti 50 @Jogador1 @Jogador2 ...
    Requer permissão de Administrador (verificada manualmente para mensagem personalizada).
    """
    # Verificação manual de permissão para permitir mensagem personalizada
    if not ctx.author.guild_permissions.administrator:
        return await ctx.send("Opa opa espertinho, você não tem poderes o suficiente para distribuir XP, vai chorar no pv do mestre!")

    if quantidade <= 0:
        return await ctx.send("❌ Forneça um valor de XP positivo.")
    if not membros:
        return await ctx.send("❌ Mencione ao menos um jogador para receber XP. Ex: `!darxpmulti 50 @Jogador1 @Jogador2`")

    resultados = []
    upados = []
    ja_max = []
    sem_ficha = []

    for membro in membros:
        ativo_membro = get_ativo(membro.id)
        if not ativo_membro:
            sem_ficha.append(membro.display_name)
            continue
        try:
            nv, res = await adicionar_xp_logica(membro.id, ativo_membro, quantidade)
            if res == "max":
                ja_max.append(f"{membro.display_name} ({ativo_membro})")
            elif res:
                upados.append(f"{membro.display_name} ({ativo_membro}) → Nível {nv}")
            else:
                resultados.append(f"{membro.display_name} ({ativo_membro}) recebeu {quantidade} XP")
        except Exception:
            resultados.append(f"{membro.display_name} ({ativo_membro}) — erro ao aplicar XP")

    emb = discord.Embed(title="🎖️ Distribuição de XP em Grupo", color=discord.Color.gold())
    if resultados:
        emb.add_field(name="✨ XP aplicado", value="\n".join(resultados), inline=False)
    if upados:
        emb.add_field(name="🎉 Subiram de nível", value="\n".join(upados), inline=False)
    if ja_max:
        emb.add_field(name="🏆 Já no nível máximo", value="\n".join(ja_max), inline=False)
    if sem_ficha:
        emb.add_field(name="❌ Sem ficha ativa", value="\n".join(sem_ficha), inline=False)

    if not (resultados or upados or ja_max):
        await ctx.send("❌ Nenhum XP foi aplicado. Verifique se os jogadores mencionados têm fichas ativas.")
        return

    await ctx.send(embed=emb)


# ----------------------------
# Editar ficha
# ----------------------------
@bot.command()
async def editar(ctx, atributo: str, *, novo_valor: str):
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use !set primeiro.")
    mapa = {"nome": "nome", "foto": "foto_url", "forca": "forca", "vel": "velocidade", "esq": "esquiva", "const": "constituicao", "atord": "atordoamento", "peste": "peste", "doenca": "doencas", "sangra": "sangramento", "debuff": "debuff", "nivel": "nivel"}
    atr = atributo.lower()
    if atr not in mapa:
        return await ctx.send("❌ Atributo inválido.")
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    try:
        if atr == "nivel":
            cursor.execute("UPDATE fichas SET nivel = ?, xp = 0 WHERE user_id = ? AND nome = ?", (int(novo_valor), str(ctx.author.id), ativo))
        elif atr == "const":
            cursor.execute("SELECT constituicao, vida FROM fichas WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return await ctx.send("❌ Ficha não encontrada.")
            const_atual, vida_atual = row
            novo_const = int(novo_valor)
            delta = novo_const - (const_atual or 0)
            nova_vida = (vida_atual or 0) + (delta * 5)
            if nova_vida < 0:
                nova_vida = 0
            cursor.execute("UPDATE fichas SET constituicao = ?, vida = ? WHERE user_id = ? AND nome = ?", (novo_const, nova_vida, str(ctx.author.id), ativo))
        else:
            cursor.execute(f"UPDATE fichas SET {mapa[atr]} = ? WHERE user_id = ? AND nome = ?", (novo_valor.strip(), str(ctx.author.id), ativo))
        conn.commit()
        await ctx.send(f"✨ **{atr.capitalize()}** de {ativo} atualizado!")
    except Exception as e:
        await ctx.send(f"❌ Erro ao editar: {e}")
    finally:
        conn.close()

# ----------------------------
# Rolagens e utilitários de teste
# ----------------------------
@bot.command()
async def rolar(ctx, atributo: str, bonus: int = 0):
    """
    Rola um d20 contra um atributo com bônus temporário opcional.
    Uso:
      !rolar esquiva
      !rolar esquiva 2   -> aplica +2 ao limite apenas nesta rolagem
      !rolar forca -1    -> aplica -1 ao limite (penalidade temporária)
    """
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use !set primeiro.")
    mapa = {
        "forca": "forca", "velocidade": "velocidade", "esquiva": "esquiva",
        "constituicao": "constituicao", "atordoamento": "atordoamento",
        "peste": "peste", "doenca": "doencas", "sangramento": "sangramento", "debuff": "debuff"
    }
    atr = atributo.lower()
    if atr not in mapa:
        return await ctx.send("❌ Atributo inválido. Use: forca, velocidade, esquiva, constituicao, atordoamento, peste, doenca, sangramento, debuff.")
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute(f"SELECT {mapa[atr]} FROM fichas WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
    row = cursor.fetchone()
    conn.close()
    val = (row[0] or 0) if row else 0

    # rola d20
    dado = random.randint(1, 20)
    limite_original = val
    limite_efetivo = val + (bonus or 0)

    # lógica de resultado (1 = crítico de sucesso, 20 = falha crítica)
    if dado == 1:
        titulo, cor = f"🌟 SUCESSO CRÍTICO em {atr.capitalize()}!", 0xffd700
        # Mensagens especiais para críticos positivos por atributo
        if atr == "esquiva":
            frase = "Uma dádiva dos ninjas, você esquiva facilmente!"
        elif atr == "forca":
            frase = "Birrrll aqui é bodybuilder, porra!"
        elif atr == "velocidade":
            frase = "Zuuuummmm!"
        else:
            frase = "🥷 **Sucesso absoluto!**"
    elif dado == 20:
        titulo, cor, frase = "💀 FALHA CRÍTICA!", 0x000000, "Xih... Você tirou 20. Se fodeu."
    elif dado <= limite_efetivo:
        titulo, cor, frase = "✅ SUCESSO!", 0x2ecc71, "Mandou bem!"
    else:
        titulo, cor, frase = "❌ FALHA!", 0xe74c3c, "Não foi dessa vez..."

    emb = discord.Embed(title=titulo, color=cor, description=frase)
    emb.add_field(name="🎲 Dado (d20)", value=f"**{dado}**", inline=True)
    emb.add_field(name="📏 Limite", value=f"**{limite_original}**", inline=True)
    emb.add_field(name="➕ Bônus temporário", value=f"**{bonus}**", inline=True)
    emb.add_field(name="📈 Limite efetivo", value=f"**{limite_efetivo}**", inline=False)
    emb.set_footer(text=f"Personagem: {ativo}")
    await ctx.send(embed=emb)

@bot.command()
async def precisão(ctx):
    await ctx.send(embed=discord.Embed(title="🎯 Precisão", description=f"Resultado: **{random.randint(1, 20)}**", color=0x3498db))

@bot.command()
async def intuição(ctx):
    await ctx.send(embed=discord.Embed(title="🧠 Intuição", description=f"Resultado: **{random.randint(1, 20)}**", color=0x9b59b6))

@bot.command()
async def percepção(ctx):
    d = random.randint(1, 6)
    msg, cor = ("🌟 **CRÍTICO! Tá afiando, em?!**", 0xf1c40f) if d == 6 else (f"Resultado: **{d}**", 0x2ecc71)
    await ctx.send(embed=discord.Embed(title="👀 Percepção", description=msg, color=cor))

# ----------------------------
# Skills: adicionar, editar, listar, info, executar, remover
# ----------------------------
@bot.command()
async def addskill(ctx, nome: str, dano: str, tipo: str = "dano", *, desc: str = ""):
    """
    Cadastra uma skill.
    Uso:
      !addskill "Granada de Praga" 2d6 dano Causa peste
      !addskill "Cura Leve" 2d6 cura Restaura vida ao alvo
    - tipo: 'dano' (padrão) ou 'cura'
    - nome: use aspas se tiver espaços
    """
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use `!set` primeiro.")
    tipo_clean = tipo.lower().strip()
    if tipo_clean not in ("dano", "cura", "heal", "curar"):
        return await ctx.send("❌ Tipo inválido. Use `dano` ou `cura`.")
    if tipo_clean in ("heal", "curar"):
        tipo_clean = "cura"
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    try:
        cursor.execute('''INSERT OR REPLACE INTO skills (user_id, nome_personagem, nome_skill, dano_formula, descricao, tipo)
                          VALUES (?, ?, ?, ?, ?, ?)''',
                       (str(ctx.author.id), ativo, nome.lower().strip(), dano.strip(), desc.strip(), tipo_clean))
        conn.commit()
        await ctx.send(f"💥 Skill **{nome}** ({tipo_clean}) adicionada para **{ativo}**!")
    except Exception as e:
        await ctx.send(f"❌ Erro ao adicionar skill: {e}")
    finally:
        conn.close()

@bot.command()
async def editskill(ctx, nome: str, campo: str, *, valor: str):
    """
    Edita campo de skill. Campos válidos: dano, desc, tipo
    Ex: !editskill cura dano 3d6
    """
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use `!set` primeiro.")
    mapa = {"dano": "dano_formula", "desc": "descricao", "tipo": "tipo"}
    campo_low = campo.lower().strip()
    if campo_low not in mapa:
        return await ctx.send("❌ Escolha `dano`, `desc` ou `tipo`.")
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    try:
        cursor.execute(f"UPDATE skills SET {mapa[campo_low]} = ? WHERE user_id = ? AND nome_personagem = ? AND nome_skill = ?",
                       (valor.strip(), str(ctx.author.id), ativo, nome.lower().strip()))
        sucesso = cursor.rowcount > 0
        conn.commit()
        await ctx.send(f"🆙 Skill **{nome}** de {ativo} atualizada!" if sucesso else "❌ Skill não encontrada.")
    except Exception as e:
        await ctx.send(f"❌ Erro ao editar skill: {e}")
    finally:
        conn.close()

@bot.command(name="removeskill", aliases=["excluirskill", "deleteskill"])
async def remove_skill(ctx, *, nome: str):
    """
    Remove uma skill do personagem ativo.
    Uso: !removeskill "Nome da Skill"
    """
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use `!set` primeiro.")
    nome_clean = nome.lower().strip()
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("DELETE FROM skills WHERE user_id = ? AND nome_personagem = ? AND nome_skill = ?", (str(ctx.author.id), ativo, nome_clean))
    if cursor.rowcount > 0:
        conn.commit()
        conn.close()
        await ctx.send(f"🗑️ Skill **{nome}** removida de **{ativo}**.")
    else:
        conn.close()
        await ctx.send("❌ Skill não encontrada. Verifique o nome e tente novamente.")

@bot.command(name="skills")
async def listar_skills(ctx, *, filtro: str = None):
    """
    Lista todas as skills do personagem ativo.
    Uso:
      !skills
      !skills fogo   -> lista apenas skills que contenham 'fogo' no nome ou descrição
    Exibe cada skill como um campo do embed com nome, dano, tipo e descrição completa.
    """
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use `!set` primeiro.")
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    if filtro:
        term = f"%{filtro.lower().strip()}%"
        cursor.execute("""SELECT nome_skill, dano_formula, descricao, tipo FROM skills
                          WHERE user_id = ? AND nome_personagem = ? AND
                          (LOWER(nome_skill) LIKE ? OR LOWER(descricao) LIKE ?)
                          ORDER BY nome_skill""", (str(ctx.author.id), ativo, term, term))
    else:
        cursor.execute("""SELECT nome_skill, dano_formula, descricao, tipo FROM skills
                          WHERE user_id = ? AND nome_personagem = ?
                          ORDER BY nome_skill""", (str(ctx.author.id), ativo))
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        if filtro:
            return await ctx.send(f"❌ Nenhuma skill encontrada com '{filtro}'.")
        return await ctx.send("❌ Nenhuma skill cadastrada para este personagem.")
    embeds = []
    chunk_size = 12
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i+chunk_size]
        emb = discord.Embed(title=f"🧾 Skills de {ativo}", color=0x1abc9c)
        for nome, dano, desc, tipo in chunk:
            nome_display = nome.capitalize()
            dano_display = dano or "—"
            desc_display = desc or "Sem descrição."
            tipo_display = "CURA" if (tipo or "dano").lower() == "cura" else "DANO"
            emb.add_field(name=f"{nome_display} — [{tipo_display}] {dano_display}", value=desc_display, inline=False)
        emb.set_footer(text="Use `!skillinfo NomeDaSkill` para ver detalhes e `!skill NomeDaSkill @alvo` para executar (cura).")
        embeds.append(emb)
    for emb in embeds:
        await ctx.send(embed=emb)

@bot.command(name="skillinfo")
async def skill_info(ctx, *, nome: str):
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use `!set` primeiro.")
    nome_clean = nome.lower().strip()
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("""SELECT nome_skill, dano_formula, descricao, tipo
                      FROM skills
                      WHERE user_id = ? AND nome_personagem = ? AND nome_skill = ?""",
                   (str(ctx.author.id), ativo, nome_clean))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return await ctx.send("❌ Skill não encontrada. Verifique o nome e tente novamente.")
    nome_skill, dano_formula, descricao, tipo = row
    tipo_display = "CURA" if (tipo or "dano").lower() == "cura" else "DANO"
    emb = discord.Embed(title=f"🔥 Skill: {nome_skill.capitalize()} [{tipo_display}]", color=0xff4500)
    emb.add_field(name="📝 Descrição", value=(descricao or "Sem descrição."), inline=False)
    emb.add_field(name="🎯 Fórmula", value=(dano_formula or "—"), inline=True)
    rolagens, total = rolar_dados(dano_formula) if dano_formula else (None, None)
    if rolagens:
        emb.add_field(name="🎲 Rolagem de Exemplo", value=f"`{' + '.join(map(str, rolagens))}` = **{total}**", inline=True)
    else:
        emb.add_field(name="🎲 Rolagem de Exemplo", value="Não aplicável / fórmula inválida", inline=True)
    emb.set_footer(text=f"Personagem: {ativo}")
    await ctx.send(embed=emb)

@bot.command(name="skill")
async def executar_skill(ctx, nome: str, alvo: str = None):
    """
    Executa uma skill. Para cura:
      !skill "Cura Leve" @Jogador
    Se alvo omitido, aplica no personagem ativo do autor.
    """
    autor_ativo = get_ativo(ctx.author.id)
    if not autor_ativo:
        return await ctx.send("❌ Use `!set` primeiro.")
    skill_name = nome.lower().strip()
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("""SELECT nome_skill, dano_formula, descricao, tipo FROM skills
                      WHERE user_id = ? AND nome_personagem = ? AND nome_skill = ?""",
                   (str(ctx.author.id), autor_ativo, skill_name))
    srow = cursor.fetchone()
    if not srow:
        conn.close()
        return await ctx.send("❌ Skill não encontrada na sua ficha. Verifique o nome e tente novamente.")
    nome_skill, formula, descricao, tipo = srow
    tipo = (tipo or "dano").lower()

    # Resolve alvo
    target_user_id = None
    target_personagem = None
    if ctx.message.mentions:
        membro = ctx.message.mentions[0]
        target_user_id = membro.id
        target_personagem = get_ativo(membro.id)
        if not target_personagem:
            conn.close()
            return await ctx.send(f"❌ {membro.display_name} não tem personagem ativo.")
    elif alvo:
        nome_alvo = alvo.strip()
        cursor.execute("SELECT user_id, nome FROM fichas WHERE lower(nome) = ?", (nome_alvo.lower(),))
        found = cursor.fetchone()
        if found:
            target_user_id, target_personagem = found[0], found[1]
        else:
            if nome_alvo.lower() == autor_ativo.lower():
                target_user_id = ctx.author.id
                target_personagem = autor_ativo
            else:
                conn.close()
                return await ctx.send("❌ Alvo não encontrado. Mencione o jogador ou use o nome exato do personagem.")
    else:
        target_user_id = ctx.author.id
        target_personagem = autor_ativo

    # Cura
    if tipo == "cura":
        rolagens, total = rolar_dados(formula)
        if rolagens is None:
            conn.close()
            return await ctx.send("❌ Fórmula de cura inválida. Use formato XdY (ex.: 2d6).")
        cursor.execute("SELECT constituicao, vida FROM fichas WHERE user_id = ? AND nome = ?", (str(target_user_id), target_personagem))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return await ctx.send("❌ Não encontrei a ficha do alvo.")
        constituicao_alvo, vida_atual = row
        max_hp = (constituicao_alvo or 0) * 5
        vida_atual = vida_atual if vida_atual is not None else max_hp
        nova_vida = vida_atual + total
        if nova_vida > max_hp:
            nova_vida = max_hp
        cursor.execute("UPDATE fichas SET vida = ? WHERE user_id = ? AND nome = ?", (nova_vida, str(target_user_id), target_personagem))
        conn.commit()
        conn.close()
        emb = discord.Embed(title=f"✨ {nome_skill.capitalize()} — Cura", color=0x2ecc71)
        emb.add_field(name="🧑‍⚕️ Caster", value=f"{autor_ativo}", inline=True)
        emb.add_field(name="🎯 Alvo", value=f"{target_personagem}", inline=True)
        emb.add_field(name="🎲 Rolagem", value=f"`{' + '.join(map(str, rolagens))}` = **{total}**", inline=False)
        emb.add_field(name="❤️ Vida", value=f"**{vida_atual} → {nova_vida}/{max_hp}**", inline=False)
        emb.set_footer(text=(descricao or ""))
        await ctx.send(embed=emb)
        return

    # Dano (apenas mostra rolagem e descrição; aplicação de dano é manual)
    rolagens, total = rolar_dados(formula)
    emb = discord.Embed(title=f"🔥 {nome_skill.capitalize()}", color=0xff4500, description=(descricao or ""))
    if rolagens:
        emb.add_field(name="🎲 Dados", value=f"`{' + '.join(map(str, rolagens))}`", inline=True)
        emb.add_field(name="💥 Total", value=f"**{total}**", inline=True)
    emb.set_footer(text="Use esta saída para aplicar dano manualmente no combate.")
    conn.close()
    await ctx.send(embed=emb)

# ----------------------------
# Economia: receber / gastar
# ----------------------------
@bot.command()
async def receber(ctx, *args):
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use `!set` primeiro.")
    total_verdes, err = parse_money_tokens(args)
    if err:
        return await ctx.send(err)
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("SELECT saldo FROM fichas WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return await ctx.send("❌ Ficha não encontrada.")
    novo_saldo = (row[0] or 0) + total_verdes
    cursor.execute("UPDATE fichas SET saldo = ? WHERE user_id = ? AND nome = ?", (novo_saldo, str(ctx.author.id), ativo))
    conn.commit(); conn.close()
    await ctx.send(f"💰 **{ativo}** recebeu {formatar_saldo(total_verdes)}. Saldo atual: {formatar_saldo(novo_saldo)}")

@bot.command()
async def gastar(ctx, *args):
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use `!set` primeiro.")
    total_verdes, err = parse_money_tokens(args)
    if err:
        return await ctx.send(err)
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("SELECT saldo FROM fichas WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return await ctx.send("❌ Ficha não encontrada.")
    saldo_atual = row[0] or 0
    if saldo_atual < total_verdes:
        conn.close()
        return await ctx.send(f"❌ Saldo insuficiente. Saldo atual: {formatar_saldo(saldo_atual)}")
    novo_saldo = saldo_atual - total_verdes
    cursor.execute("UPDATE fichas SET saldo = ? WHERE user_id = ? AND nome = ?", (novo_saldo, str(ctx.author.id), ativo))
    conn.commit(); conn.close()
    await ctx.send(f"💸 **{ativo}** gastou {formatar_saldo(total_verdes)}. Saldo atual: {formatar_saldo(novo_saldo)}")

# ----------------------------
# Estresse / Sanidade / HP (ferimento / curou)
# ----------------------------
@bot.command(name="estressou")
async def estressou(ctx, valor: int):
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use `!set` primeiro.")
    if valor <= 0:
        return await ctx.send("❌ Forneça um valor positivo para aumentar o estresse.")
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("SELECT estresse FROM fichas WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return await ctx.send("❌ Ficha não encontrada.")
    est_atual = row[0] or 0
    novo_est = est_atual + valor
    if novo_est > 200:
        novo_est = 200
    cursor.execute("UPDATE fichas SET estresse = ? WHERE user_id = ? AND nome = ?", (novo_est, str(ctx.author.id), ativo))
    conn.commit(); conn.close()
    await ctx.send(f"😰 **{ativo}** aumentou **{valor}** de estresse. Estresse atual: **{novo_est}/200**")
    if novo_est >= 200:
        texto = f"Essa não... Parece que **{ativo}** alcançou o limite de sua sanidade."
        emb = discord.Embed(description=texto, color=0x8b0000)
        emb.set_image(url=SANIDADE_GIF)
        await ctx.send(embed=emb)

@bot.command(name="desestressou")
async def desestressou(ctx, valor: int):
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use `!set` primeiro.")
    if valor <= 0:
        return await ctx.send("❌ Forneça um valor positivo para reduzir o estresse.")
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("SELECT estresse FROM fichas WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return await ctx.send("❌ Ficha não encontrada.")
    est_atual = row[0] or 0
    novo_est = est_atual - valor
    if novo_est < 0:
        novo_est = 0
    cursor.execute("UPDATE fichas SET estresse = ? WHERE user_id = ? AND nome = ?", (novo_est, str(ctx.author.id), ativo))
    conn.commit(); conn.close()
    await ctx.send(f"😌 **{ativo}** reduziu **{valor}** de estresse. Estresse atual: **{novo_est}/200**")

@bot.command(name="ferimento")
async def ferimento(ctx, valor: int):
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use `!set` primeiro.")
    if valor <= 0:
        return await ctx.send("❌ Forneça um valor positivo para causar dano.")
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("SELECT constituicao, vida FROM fichas WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return await ctx.send("❌ Ficha não encontrada.")
    constituicao, vida_atual = row
    max_hp = (constituicao or 0) * 5
    vida_atual = vida_atual if vida_atual is not None else max_hp
    nova_vida = vida_atual - valor
    if nova_vida < 0:
        nova_vida = 0
    cursor.execute("UPDATE fichas SET vida = ? WHERE user_id = ? AND nome = ?", (nova_vida, str(ctx.author.id), ativo))
    conn.commit(); conn.close()
    await ctx.send(f"🩸 **{ativo}** sofreu **{valor}** de dano. Vida atual: **{nova_vida}/{max_hp}**")

@bot.command(name="curou")
async def curou(ctx, valor: int):
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use `!set` primeiro.")
    if valor <= 0:
        return await ctx.send("❌ Forneça um valor positivo para curar.")
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("SELECT constituicao, vida FROM fichas WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return await ctx.send("❌ Ficha não encontrada.")
    constituicao, vida_atual = row
    max_hp = (constituicao or 0) * 5
    vida_atual = vida_atual or 0
    nova_vida = vida_atual + valor
    if nova_vida > max_hp:
        nova_vida = max_hp
    cursor.execute("UPDATE fichas SET vida = ? WHERE user_id = ? AND nome = ?", (nova_vida, str(ctx.author.id), ativo))
    conn.commit(); conn.close()
    await ctx.send(f"✨ **{ativo}** recuperou **{valor}** de vida. Vida atual: **{nova_vida}/{max_hp}**")

@bot.command(name="upararma")
async def upararma(ctx, *args):
    """
    Atualiza arma existente. Formatos aceitos:
      !upararma "Nome da Arma" nivel_inc d6_inc
      !upararma @Jogador "Nome da Arma" nivel_inc d6_inc
    Aceita nome entre aspas para suportar espaços.
    """
    if not args:
        return await ctx.send("❌ Uso: `!upararma \"Nome\" nivel_inc d6_inc`")

    # Detecta menção no conteúdo da mensagem (prioriza menção explícita)
    membro = None
    tokens = list(args)
    if ctx.message.mentions:
        membro = ctx.message.mentions[0]
        # remove a primeira token correspondente à menção dos tokens
        # (args já separa por espaços, então descartamos o primeiro token)
        tokens = tokens[1:]

    # Reconstrói nome entre aspas se necessário
    if not tokens:
        return await ctx.send("❌ Nome da arma não informado.")
    if tokens[0].startswith('"') or tokens[0].startswith("'"):
        quote = tokens[0][0]
        nome_parts = []
        consumed = 0
        for t in tokens:
            nome_parts.append(t)
            consumed += 1
            if t.endswith(quote) and len(t) > 1:
                break
        nome = " ".join(nome_parts).strip(quote).strip()
        rest = tokens[consumed:]
    else:
        nome = tokens[0]
        rest = tokens[1:]

    # Se não houve menção, alvo é o autor
    if membro is None:
        membro = ctx.author
    else:
        # se tentou atualizar arma de outro, exige permissão de administrador
        if membro != ctx.author and not ctx.author.guild_permissions.administrator:
            return await ctx.send("🔒 Você não tem permissão para atualizar a arma de outro jogador.")

    # Parse dos incrementos (preenche com zeros se faltarem)
    try:
        nivel_inc = int(rest[0]) if len(rest) >= 1 else 0
        d6_inc = int(rest[1]) if len(rest) >= 2 else 0
    except ValueError:
        return await ctx.send("❌ Argumento inválido. Use números inteiros para os incrementos. Veja `!helpdados`.")

    ativo = get_ativo(membro.id)
    if not ativo:
        return await ctx.send(f"❌ {membro.display_name} não tem um personagem ativo.")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT nivel, d6 FROM armas WHERE user_id = ? AND nome_personagem = ? AND LOWER(item_nome) = ?",
        (str(membro.id), ativo, nome.lower())
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return await ctx.send(f"❌ Arma **{nome}** não encontrada para o personagem **{ativo}** de {membro.display_name}.")

    nivel_atual, d6_atual = row
    novo_nivel = (nivel_atual or 0) + nivel_inc
    novo_d6 = (d6_atual or 0) + d6_inc

    if novo_nivel < 0 or novo_d6 < 0:
        conn.close()
        return await ctx.send("❌ Resultado inválido: nível ou d6 não podem ficar negativos.")

    try:
        cursor.execute("""UPDATE armas
                          SET nivel = ?, d6 = ?
                          WHERE user_id = ? AND nome_personagem = ? AND LOWER(item_nome) = ?""",
                       (novo_nivel, novo_d6, str(membro.id), ativo, nome.lower()))
        conn.commit()
    except Exception as e:
        conn.close()
        return await ctx.send(f"❌ Erro ao atualizar arma: {e}")

    conn.close()

    emb = discord.Embed(title="⚔️ Arma Atualizada", color=discord.Color.dark_blue())
    emb.add_field(name="👤 Jogador", value=f"{membro.display_name} ({ativo})", inline=False)
    emb.add_field(name="🔧 Arma", value=f"**{nome}**", inline=False)
    emb.add_field(name="📈 Antes", value=f"Nível: **{nivel_atual}** | D6: **{d6_atual}**", inline=False)
    emb.add_field(name="📈 Agora", value=f"Nível: **{novo_nivel}** | D6: **{novo_d6}**", inline=False)
    emb.set_footer(text="Use com cuidado — alterações são permanentes no banco de dados.")
    await ctx.send(embed=emb)



@bot.command(name="upararmadura")
async def upararmadura(ctx, *args):
    """
    Atualiza armadura existente. Formatos aceitos:
      !upararmadura "Nome da Armadura" nivel_inc d6_inc bonus_esq_inc bonus_vel_inc
      !upararmadura @Jogador "Nome da Armadura" nivel_inc d6_inc bonus_esq_inc bonus_vel_inc
    """
    # args parsing flexível
    if not args:
        return await ctx.send("❌ Uso: `!upararmadura \"Nome\" nivel_inc d6_inc bonus_esq_inc bonus_vel_inc`")

    # tenta detectar se o primeiro arg é uma menção de membro
    membro = None
    nome = None
    rest = []

    # se houver menções explícitas no ctx, prioriza a primeira menção
    if ctx.message.mentions:
        membro = ctx.message.mentions[0]
        # remove a menção do texto bruto para extrair o restante corretamente
        raw = ctx.message.content
        # pega tudo após o comando e a menção
        after = raw.split(maxsplit=2)[-1] if len(raw.split()) >= 2 else ""
        # tenta extrair nome entre aspas e os números
        # fallback simples: reconstruir args sem a primeira token de menção
        tokens = list(args)[1:]
    else:
        # sem menção: assume que o primeiro arg é o nome (possivelmente entre aspas)
        tokens = list(args)

    # Reconstrói nome se estiver entre aspas (suporta nomes com espaços)
    if tokens:
        # se o primeiro token começa com aspas, junta até fechar aspas
        if tokens[0].startswith('"') or tokens[0].startswith("'"):
            quote = tokens[0][0]
            nome_parts = []
            consumed = 0
            for t in tokens:
                nome_parts.append(t)
                consumed += 1
                if t.endswith(quote) and len(t) > 1:
                    break
            nome = " ".join(nome_parts).strip(quote).strip()
            rest = tokens[consumed:]
        else:
            # se não tem aspas, pega o primeiro token como nome simples
            nome = tokens[0]
            rest = tokens[1:]
    else:
        return await ctx.send("❌ Nome da armadura não informado.")

    # se membro não foi definido via menção, atualiza do autor
    if membro is None:
        membro = ctx.author
    else:
        # se tentou atualizar armadura de outro, exige permissão de administrador
        if membro != ctx.author and not ctx.author.guild_permissions.administrator:
            return await ctx.send("🔒 Você não tem permissão para atualizar a armadura de outro jogador.")

    # parse dos incrementos (preenche com zeros se faltarem)
    try:
        nivel_inc = int(rest[0]) if len(rest) >= 1 else 0
        d6_inc = int(rest[1]) if len(rest) >= 2 else 0
        bonus_esq_inc = int(rest[2]) if len(rest) >= 3 else 0
        bonus_vel_inc = int(rest[3]) if len(rest) >= 4 else 0
    except ValueError:
        return await ctx.send("❌ Argumento inválido. Use números inteiros para os incrementos. Veja `!helpdados`.")

    ativo = get_ativo(membro.id)
    if not ativo:
        return await ctx.send(f"❌ {membro.display_name} não tem um personagem ativo.")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT nivel, d6, bonus_esquiva, bonus_velocidade FROM armaduras WHERE user_id = ? AND nome_personagem = ? AND LOWER(item_nome) = ?",
        (str(membro.id), ativo, nome.lower())
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return await ctx.send(f"❌ Armadura **{nome}** não encontrada para o personagem **{ativo}** de {membro.display_name}.")

    nivel_atual, d6_atual, bonus_esq_atual, bonus_vel_atual = row
    novo_nivel = (nivel_atual or 0) + nivel_inc
    novo_d6 = (d6_atual or 0) + d6_inc
    novo_bonus_esq = (bonus_esq_atual or 0) + bonus_esq_inc
    novo_bonus_vel = (bonus_vel_atual or 0) + bonus_vel_inc

    if novo_nivel < 0 or novo_d6 < 0:
        conn.close()
        return await ctx.send("❌ Resultado inválido: nível ou d6 não podem ficar negativos.")

    try:
        cursor.execute("""UPDATE armaduras
                          SET nivel = ?, d6 = ?, bonus_esquiva = ?, bonus_velocidade = ?
                          WHERE user_id = ? AND nome_personagem = ? AND LOWER(item_nome) = ?""",
                       (novo_nivel, novo_d6, novo_bonus_esq, novo_bonus_vel, str(membro.id), ativo, nome.lower()))
        conn.commit()
    except Exception as e:
        conn.close()
        return await ctx.send(f"❌ Erro ao atualizar armadura: {e}")

    conn.close()

    emb = discord.Embed(title="🛡️ Armadura Atualizada", color=discord.Color.dark_blue())
    emb.add_field(name="👤 Jogador", value=f"{membro.display_name} ({ativo})", inline=False)
    emb.add_field(name="🔧 Armadura", value=f"**{nome}**", inline=False)
    emb.add_field(name="📈 Antes", value=f"Nível: **{nivel_atual}** | D6: **{d6_atual}** | +Esq: **{bonus_esq_atual}** | +Vel: **{bonus_vel_atual}**", inline=False)
    emb.add_field(name="📈 Agora", value=f"Nível: **{novo_nivel}** | D6: **{novo_d6}** | +Esq: **{novo_bonus_esq}** | +Vel: **{novo_bonus_vel}**", inline=False)
    emb.set_footer(text="Use com cuidado — alterações são permanentes no banco de dados.")
    await ctx.send(embed=emb)


# ----------------------------
# Equipamento: adicionar / remover armas e armaduras
# ----------------------------
@bot.command(name="adicionar")
async def adicionar_item(ctx, tipo: str, nome: str, nivel: int, d6: int, bonus_esq: int = 0, bonus_vel: int = 0):
    """
    Uso:
      !adicionar arma "Nome da Arma" Nivel D6
      !adicionar armadura "Nome da Armadura" Nivel D6 [bonus_esq] [bonus_vel]
    """
    tipo = tipo.lower()
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use `!set` primeiro.")
    if nivel < 0 or d6 <= 0:
        return await ctx.send("❌ Nível deve ser >= 0 e D6 deve ser >= 1.")
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    if tipo == "arma":
        try:
            cursor.execute("INSERT OR REPLACE INTO armas (user_id, nome_personagem, item_nome, nivel, d6) VALUES (?, ?, ?, ?, ?)",
                           (str(ctx.author.id), ativo, nome.strip(), nivel, d6))
            cursor.execute("UPDATE fichas SET arma_equipada = ? WHERE user_id = ? AND nome = ?", (nome.strip(), str(ctx.author.id), ativo))
            conn.commit()
            await ctx.send(f"⚔️ Arma **{nome}** (Nível {nivel} | {d6}d6) cadastrada e equipada em **{ativo}**.")
        except Exception as e:
            await ctx.send(f"❌ Erro ao adicionar arma: {e}")
        finally:
            conn.close()
    elif tipo == "armadura":
        try:
            cursor.execute("SELECT armadura_equipada FROM fichas WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
            cur = cursor.fetchone()
            atual_arm = cur[0] if cur else None
            if atual_arm:
                cursor.execute("SELECT bonus_esquiva, bonus_velocidade FROM armaduras WHERE user_id = ? AND nome_personagem = ? AND item_nome = ?", (str(ctx.author.id), ativo, atual_arm))
                old = cursor.fetchone()
                if old:
                    old_esq, old_vel = old[0] or 0, old[1] or 0
                    if old_esq or old_vel:
                        cursor.execute("UPDATE fichas SET esquiva = esquiva - ?, velocidade = velocidade - ? WHERE user_id = ? AND nome = ?", (old_esq, old_vel, str(ctx.author.id), ativo))
            cursor.execute("INSERT OR REPLACE INTO armaduras (user_id, nome_personagem, item_nome, nivel, d6, bonus_esquiva, bonus_velocidade) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (str(ctx.author.id), ativo, nome.strip(), nivel, d6, bonus_esq, bonus_vel))
            if bonus_esq or bonus_vel:
                cursor.execute("UPDATE fichas SET esquiva = esquiva + ?, velocidade = velocidade + ? WHERE user_id = ? AND nome = ?", (bonus_esq, bonus_vel, str(ctx.author.id), ativo))
            cursor.execute("UPDATE fichas SET armadura_equipada = ? WHERE user_id = ? AND nome = ?", (nome.strip(), str(ctx.author.id), ativo))
            conn.commit()
            await ctx.send(f"🛡️ Armadura **{nome}** (Nível {nivel} | {d6}d6) cadastrada e equipada em **{ativo}**. Bônus aplicados: Esquiva +{bonus_esq}, Vel +{bonus_vel}.")
        except Exception as e:
            await ctx.send(f"❌ Erro ao adicionar armadura: {e}")
        finally:
            conn.close()
    else:
        conn.close()
        await ctx.send("❌ Tipo inválido. Use `arma` ou `armadura`.")

@bot.command(name="remover")
async def remover_item(ctx, tipo: str, *, nome: str):
    tipo = tipo.lower()
    ativo = get_ativo(ctx.author.id)
    if not ativo:
        return await ctx.send("❌ Use `!set` primeiro.")
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    if tipo == "arma":
        cursor.execute("SELECT arma_equipada FROM fichas WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
        cur = cursor.fetchone()
        arma_eq = cur[0] if cur else None
        try:
            cursor.execute("DELETE FROM armas WHERE user_id = ? AND nome_personagem = ? AND item_nome = ?", (str(ctx.author.id), ativo, nome.strip()))
            if arma_eq and arma_eq == nome.strip():
                cursor.execute("UPDATE fichas SET arma_equipada = NULL WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
            conn.commit()
            await ctx.send(f"🗑️ Arma **{nome}** removida dos registros de **{ativo}**.")
        except Exception as e:
            await ctx.send(f"❌ Erro ao remover arma: {e}")
        finally:
            conn.close()
    elif tipo == "armadura":
        cursor.execute("SELECT armadura_equipada FROM fichas WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
        cur = cursor.fetchone()
        arm_eq = cur[0] if cur else None
        try:
            cursor.execute("SELECT bonus_esquiva, bonus_velocidade FROM armaduras WHERE user_id = ? AND nome_personagem = ? AND item_nome = ?", (str(ctx.author.id), ativo, nome.strip()))
            old = cursor.fetchone()
            if old:
                old_esq, old_vel = old[0] or 0, old[1] or 0
            else:
                old_esq, old_vel = 0, 0
            cursor.execute("DELETE FROM armaduras WHERE user_id = ? AND nome_personagem = ? AND item_nome = ?", (str(ctx.author.id), ativo, nome.strip()))
            if arm_eq and arm_eq == nome.strip():
                if old_esq or old_vel:
                    cursor.execute("UPDATE fichas SET esquiva = esquiva - ?, velocidade = velocidade - ? WHERE user_id = ? AND nome = ?", (old_esq, old_vel, str(ctx.author.id), ativo))
                cursor.execute("UPDATE fichas SET armadura_equipada = NULL WHERE user_id = ? AND nome = ?", (str(ctx.author.id), ativo))
            conn.commit()
            await ctx.send(f"🗑️ Armadura **{nome}** removida dos registros de **{ativo}** e bônus (se houver) desfeitos.")
        except Exception as e:
            await ctx.send(f"❌ Erro ao remover armadura: {e}")
        finally:
            conn.close()
    else:
        conn.close()
        await ctx.send("❌ Tipo inválido. Use `arma` ou `armadura`.")

# ----------------------------
# Comandos auxiliares: set, minhasfichas, excluirficha
# ----------------------------
@bot.command()
async def set(ctx, *, nome: str):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("SELECT nome FROM fichas WHERE user_id = ? AND nome = ?", (str(ctx.author.id), nome.strip()))
    if cursor.fetchone():
        cursor.execute("INSERT OR REPLACE INTO ativo (user_id, nome_personagem) VALUES (?, ?)", (str(ctx.author.id), nome.strip()))
        conn.commit(); await ctx.send(f"✅ Ativo: **{nome.strip()}**")
    else:
        await ctx.send("❌ Ficha não encontrada.")
    conn.close()

@bot.command()
async def minhasfichas(ctx):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("SELECT nome FROM fichas WHERE user_id = ?", (str(ctx.author.id),))
    fichas = cursor.fetchall(); ativo = get_ativo(ctx.author.id); conn.close()
    if fichas:
        lista = "\n".join([f"• **{f[0]}** {'🌟 (ATIVO)' if f[0] == ativo else ''}" for f in fichas])
        await ctx.send(f"📚 **Seus Personagens:**\n{lista}")
    else:
        await ctx.send("❓ Nenhuma ficha encontrada.")

@bot.command()
async def excluirficha(ctx, *, nome: str):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("DELETE FROM fichas WHERE user_id = ? AND nome = ?", (str(ctx.author.id), nome.strip()))
    cursor.execute("DELETE FROM skills WHERE user_id = ? AND nome_personagem = ?", (str(ctx.author.id), nome.strip()))
    cursor.execute("DELETE FROM armas WHERE user_id = ? AND nome_personagem = ?", (str(ctx.author.id), nome.strip()))
    cursor.execute("DELETE FROM armaduras WHERE user_id = ? AND nome_personagem = ?", (str(ctx.author.id), nome.strip()))
    conn.commit(); conn.close(); await ctx.send(f"🗑️ **{nome}** excluído.")
# ----------------------------
# Handler global de erros de comando
# ----------------------------
@bot.event
async def on_command_error(ctx, error):
    # Evita duplicar mensagens se outro handler já tratou
    if hasattr(ctx.command, "on_error"):
        return

    # Comando não encontrado -> sugere helpdados
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(f"❓ Comando não reconhecido. Dê uma olhada em `!helpdados` para os comandos disponíveis.")
        return

    # Falta de argumento obrigatório
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Faltou um argumento: `{error.param}`. Veja `!helpdados` para o formato correto do comando.")
        return

    # Argumento inválido (tipo errado)
    if isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argumento inválido. Verifique os tipos/valores e consulte `!helpdados`.")
        return

    # Muitos argumentos
    if isinstance(error, commands.TooManyArguments):
        await ctx.send("❌ Muitos argumentos fornecidos. Confira o formato em `!helpdados`.")
        return

    # Permissões
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("🔒 Você não tem permissão para usar este comando.")
        return

    # Erros inesperados: loga no console e avisa o usuário de forma genérica
    # (mantemos a mensagem curta para não vazar detalhes internos)
    print(f"[ERROR] Comando: {ctx.command} | Usuário: {ctx.author} | Erro: {error}")
    await ctx.send("⚠️ Ocorreu um erro ao executar o comando. Tente novamente ou consulte `!helpdados`.")


# ----------------------------
# Evento on_ready e execução do bot
# ----------------------------
@bot.event
async def on_ready():
    print(f'✅ Bot RPG {bot.user} online e completo!')

# Substitua pelo seu token real antes de rodar
bot.run('bot token')
