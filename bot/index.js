const { Client, LocalAuth } = require('whatsapp-web.js')
const qrcode = require('qrcode-terminal')
const axios = require('axios')

// Configuração vem do .env da raiz do projeto (veja o .env.example)
const API = process.env.API_URL || 'http://127.0.0.1:8000'
const NUMERO_ATELIE = process.env.NUMERO_ATELIE
const SENHA_ADMIN = process.env.SENHA_ADMIN
const NUMEROS_BLOQUEADOS = (process.env.NUMEROS_BLOQUEADOS || '')
    .split(',')
    .map(n => n.trim())
    .filter(Boolean)

if (!NUMERO_ATELIE || !SENHA_ADMIN || !process.env.BOT_API_KEY) {
    console.error('Faltam variáveis no .env: NUMERO_ATELIE, SENHA_ADMIN e BOT_API_KEY.')
    process.exit(1)
}

// a API exige essa chave em todas as rotas
axios.defaults.headers.common['X-API-Key'] = process.env.BOT_API_KEY

const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: { args: ['--no-sandbox'] }
})

client.on('qr', (qr) => {
    console.log('Escaneie o QR Code abaixo com o WhatsApp:')
    qrcode.generate(qr, { small: true })
})

let botIniciadoEm

client.on('ready', () => {
    botIniciadoEm = Date.now()
    console.log('Bot conectado ao WhatsApp!')
})

// Ignora status, grupos e números bloqueados
client.on('message', async (msg) => {

    if (msg.from === 'status@broadcast') return
    if (msg.from.includes('@g.us')) return
    // ao reconectar, o WhatsApp entrega mensagens antigas de uma vez: ignora
    if (msg.timestamp * 1000 < botIniciadoEm) return
    if (!['chat', 'text'].includes(msg.type)) return
    if (msg.isStatus) return
    if (msg.fromMe) return

    // O remetente pode vir como @c.us (número) ou @lid (id interno do WhatsApp).
    // No segundo caso o número real vem do contato.
    const fromClean = msg.from.replace('@c.us', '').replace('@lid', '')
    if (!fromClean.startsWith('55') && !msg.from.includes('@lid')) return

    let telefone
    if (msg.from.includes('@lid')) {
        try {
            const contato = await msg.getContact()
            telefone = contato.number.replace(/^55/, '')
        } catch {
            console.log('Não foi possível obter número do contato @lid')
            return
        }
    } else {
        telefone = msg.from.replace('@c.us', '').replace(/^55/, '')
    }

    const texto = msg.body.trim()
    if (!texto) return
    // Ignora mensagens que são só emojis
    const somenteEmoji = /^[\u{1F000}-\u{1FFFF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\s]+$/u
    if (somenteEmoji.test(texto)) return
    if (NUMEROS_BLOQUEADOS.includes(telefone)) return


    const sessao = await carregarSessao(telefone)

    try {
        await handleMensagem(msg, telefone, texto, sessao)
    } catch (err) {
        console.error(err)
        msg.reply('❌ Ocorreu um erro. Tente novamente.')
    } finally {
        await salvarSessao(telefone)
    }
})

const sessoes = {}

// O estado da conversa de cada cliente fica na API (tabela sessoes), assim um
// restart do bot não faz ninguém perder o agendamento que estava preenchendo.
async function carregarSessao(telefone) {
    try {
        const { data } = await axios.get(`${API}/sessoes/${telefone}`)
        sessoes[telefone] = data
    } catch {
        sessoes[telefone] = { etapa: 'menu' }
    }
    return sessoes[telefone]
}

async function salvarSessao(telefone) {
    try {
        await axios.post(`${API}/sessoes/${telefone}`, sessoes[telefone])
    } catch (err) {
        console.error('Erro ao salvar sessão:', err.message)
    }
}

async function handleMensagem(msg, telefone, texto, sessao) {

    // Permite cancelar o fluxo em qualquer etapa
    if (texto.toLowerCase() === 'cancelar' && sessao.etapa !== 'menu') {
        sessao.etapa = 'menu'
        return msg.reply(
            '❌ Operação cancelada!\n\n' +
            '💅 *Bem-vinda ao Ateliê!*\n\n' +
            'O que deseja fazer?\n\n' +
            '1️⃣ Ver serviços disponíveis\n' +
            '2️⃣ Agendar horário\n' +
            '3️⃣ Ver meus agendamentos\n' +
            '4️⃣ Cancelar agendamento\n' +
            '5️⃣ Ver endereço\n\n' +
            '6️⃣ Falar com o ateliê\n\n' +
            'Digite o número da opção desejada.'
        )
    }

    // Resposta ao lembrete do dia anterior. Quem coloca a cliente nessa etapa é o
    // servidor HTTP no fim do arquivo, quando o scheduler pede o envio.
    if (sessao.etapa === 'confirmar_lembrete') {
        if (texto.toLowerCase() === 'sim') {
            try {
                await axios.patch(`${API}/agendamentos/${sessao.confirmar_id}/confirmar`)
                sessao.etapa = 'menu'
                return msg.reply(
                    '✅ Presença confirmada! Te esperamos 💅\n\n' +
                    'Digite *0* para ver o menu.'
                )
            } catch (err) {
                sessao.etapa = 'menu'
                return msg.reply('❌ Erro ao confirmar. Digite *0* para o menu.')
            }
        }

        if (texto.toLowerCase() === 'não' || texto.toLowerCase() === 'nao') {
            try {
                const { data } = await axios.patch(`${API}/agendamentos/${sessao.confirmar_id}/cancelar?telefone=${telefone}`)
                sessao.etapa = 'menu'
                if (data.taxa) {
                    return msg.reply(
                        '❌ Agendamento cancelado.\n\n' +
                        '⚠️ Como o cancelamento foi feito com menos de 10h, ' +
                        'será cobrado *50%* no próximo agendamento.\n\n' +
                        'Digite *0* para ver o menu.'
                    )
                }
                return msg.reply('❌ Agendamento cancelado.\n\nDigite *0* para ver o menu.')
            } catch (err) {
                sessao.etapa = 'menu'
                return msg.reply('❌ Erro ao cancelar. Digite *0* para o menu.')
            }
        }

        return msg.reply('Por favor, digite *sim* para confirmar ou *não* para cancelar.')
    }

    // ACESSO ADMIN
    if (texto.startsWith('admin ')) {
        const senha = texto.split(' ')[1]
        if (senha !== SENHA_ADMIN) {
            return msg.reply('❌ Senha incorreta.')
        }
        sessao.etapa = 'admin'
        return msg.reply(
            '🔐 *Painel Admin*\n\n' +
            '1️⃣ Ver agendamentos de hoje\n' +
            '2️⃣ Ver agendamentos por data\n' +
            '3️⃣ Cancelar agendamento de cliente\n' +
            '4️⃣ Ver todas as clientes\n' +
            '0️⃣ Sair do admin\n\n' +
            'Digite o número da opção.'
        )
    }

    // MENU ADMIN
    if (sessao.etapa === 'admin') {
        if (texto === '0') {
            sessao.etapa = 'menu'
            return msg.reply('✅ Saindo do admin.\n\nDigite qualquer coisa para ver o menu.')
        }

        if (texto === '1') {
            try {
                const hoje = new Date().toLocaleDateString('pt-BR')
                const { data } = await axios.get(`${API}/admin/agendamentos?data=${encodeURIComponent(hoje)}`)
                if (data.length === 0) {
                    return msg.reply('📭 Nenhum agendamento para hoje!\n\nDigite *0* para sair do admin.')
                }
                let resposta = `📅 *Agendamentos de hoje:*\n\n`
                data.forEach(a => {
                    const horario = new Date(a.data_hora).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
                    resposta += `🕐 *${horario}* — ${a.cliente.nome}\n`
                    resposta += `   ✂️ ${a.servico.nome}\n`
                    resposta += `   📞 ${a.cliente.telefone}\n`
                    resposta += `   🆔 ID: ${a.id}\n\n`
                })
                resposta += 'Digite *0* para sair do admin.'
                return msg.reply(resposta)
            } catch (err) {
                return msg.reply('❌ Erro ao buscar agendamentos.')
            }
        }

        if (texto === '2') {
            sessao.etapa = 'admin_ver_data'
            return msg.reply('📅 Digite a data que deseja consultar:\n\nFormato: *DD/MM/AAAA*')
        }

        if (texto === '3') {
            sessao.etapa = 'admin_cancelar_id'
            return msg.reply('❌ Digite o *ID* do agendamento que deseja cancelar:')
        }

        if (texto === '4') {
            try {
                const { data } = await axios.get(`${API}/admin/clientes`)
                if (data.length === 0) {
                    return msg.reply('📭 Nenhuma cliente cadastrada.\n\nDigite *0* para sair do admin.')
                }
                let resposta = '👥 *Clientes cadastradas:*\n\n'
                data.forEach(c => {
                    resposta += `👤 *${c.nome}*\n`
                    resposta += `   📞 ${c.telefone}\n\n`
                })
                resposta += 'Digite *0* para sair do admin.'
                return msg.reply(resposta)
            } catch (err) {
                return msg.reply('❌ Erro ao buscar clientes.')
            }
        }
    }

    if (sessao.etapa === 'admin_ver_data') {
        try {
            const { data } = await axios.get(`${API}/admin/agendamentos?data=${encodeURIComponent(texto)}`)
            sessao.etapa = 'admin'
            if (data.length === 0) {
                return msg.reply(`📭 Nenhum agendamento para ${texto}.\n\nDigite *0* para sair do admin.`)
            }
            let resposta = `📅 *Agendamentos de ${texto}:*\n\n`
            data.forEach(a => {
                const horario = new Date(a.data_hora).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
                resposta += `🕐 *${horario}* — ${a.cliente.nome}\n`
                resposta += `   ✂️ ${a.servico.nome}\n`
                resposta += `   📞 ${a.cliente.telefone}\n`
                resposta += `   🆔 ID: ${a.id}\n\n`
            })
            resposta += 'Digite *0* para sair do admin.'
            return msg.reply(resposta)
        } catch (err) {
            sessao.etapa = 'admin'
            return msg.reply('❌ Data inválida. Voltando ao admin.\n\nDigite *0* para sair.')
        }
    }

    if (sessao.etapa === 'admin_cancelar_id') {
        const id = parseInt(texto)
        if (isNaN(id)) {
            return msg.reply('❌ ID inválido. Digite apenas o número:')
        }
        try {
            await axios.patch(`${API}/admin/agendamentos/${id}/cancelar`)
            sessao.etapa = 'admin'
            return msg.reply('✅ Agendamento cancelado!\n\nDigite *0* para sair do admin.')
        } catch (err) {
            sessao.etapa = 'admin'
            const mensagem = err.response?.data?.detail || 'Erro ao cancelar.'
            return msg.reply(`❌ ${mensagem}\n\nDigite *0* para sair do admin.`)
        }
    }

    // MENU PRINCIPAL
    if (sessao.etapa === 'menu') {
        if (texto === '1') {
            const { data } = await axios.get(`${API}/servicos`)
            let resposta = '📋 *Serviços disponíveis:*\n\n'
            data.forEach(s => {
                resposta += `*${s.id}. ${s.nome}*\n`
                resposta += `   💰 R$ ${s.preco}\n`
                resposta += `   ⏱️ ${s.duracao_min} minutos\n\n`
            })
            resposta += 'Digite *0* para voltar ao menu.'
            return msg.reply(resposta)
        }

        if (texto === '2') {
            sessao.etapa = 'agendar_nome'
            return msg.reply('📝 Vamos agendar! Primeiro, qual é o seu *nome completo*?')
        }

        if (texto === '3') {
            try {
                const { data } = await axios.get(`${API}/agendamentos/${telefone}`)
                if (data.length === 0) {
                    return msg.reply('📭 Você não tem agendamentos futuros.\n\nDigite *0* para voltar ao menu.')
                }
                let resposta = '📅 *Seus agendamentos:*\n\n'
                data.forEach(a => {
                    resposta += `*ID: ${a.id}*\n`
                    resposta += `✂️ ${a.servico.nome}\n`
                    resposta += `📅 ${new Date(a.data_hora).toLocaleString('pt-BR')}\n\n`
                })
                resposta += 'Digite *0* para voltar ao menu.'
                return msg.reply(resposta)
            } catch (err) {
                console.log('Erro opção 3:', err.response?.data || err.message)
                return msg.reply('📭 Você não tem agendamentos futuros.\n\nDigite *0* para voltar ao menu.')
            }
        }

        if (texto === '4') {
            sessao.etapa = 'cancelar_id'
            return msg.reply('❌ Digite o *ID* do agendamento que deseja cancelar:')
        }

        if (texto === '5') {
            return msg.reply(
                '📍 *Localização do Ateliê*\n\n' +
                '🏠 Endereço: \n' +
                'Rua Exemplo, 123 - Cidade/UF\n\n' +
                '🗺️ Google Maps: https://maps.app.goo.gl/EXEMPLO\n\n' +
                '🕐 *Horários de atendimento:*\n' +
                'Segunda a Sexta: 07:00 às 16:00\n' +
                'Sábado: 06:00 às 10:00\n\n' +
                'Digite *0* para voltar ao menu.'
            )
        }

        if (texto === '6') {
            sessao.etapa = 'falar_com_atelie'

            try {
                let nomeCliente = telefone
                try {
                    const { data: cliente } = await axios.get(`${API}/clientes/${telefone}`)
                    nomeCliente = cliente.nome
                } catch {}

                await client.sendMessage(`${NUMERO_ATELIE}@c.us`,
                    `💬 *Atendimento solicitado!*\n\n` +
                    `A cliente quer falar diretamente com você.\n` +
                    `👤 Nome: ${nomeCliente}\n` +
                    `📞 Número: ${telefone}\n\n` +
                    `Responda diretamente para ela no WhatsApp.`
                )
            } catch (errWhats) {
                console.error('Aviso WhatsApp falhou:', errWhats.message)
            }

            // Envia e-mail também
            try {
                await axios.post(`${API}/email-atendimento`, { telefone })
            } catch (errEmail) {
                console.error('E-mail falhou:', errEmail.message)
            }

            return msg.reply(
                '💬 *Atendimento humano solicitado!*\n\n' +
                'A equipe do ateliê foi avisada e responde em breve! 😊\n\n' +
                '_Digite *cancelar* para voltar ao menu._'
            )
        }

        if (texto === '0') {
            return msg.reply(
                '💅 *Bem-vinda ao Ateliê!*\n\n' +
                'O que deseja fazer?\n\n' +
                '1️⃣ Ver serviços disponíveis\n' +
                '2️⃣ Agendar horário\n' +
                '3️⃣ Ver meus agendamentos\n' +
                '4️⃣ Cancelar agendamento\n' +
                '5️⃣ Ver endereço\n\n' +
                '6️⃣ Falar com o ateliê\n\n' +
                'Digite o número da opção desejada.'
            )
        }

        // Verifica se é cliente nova ou conhecida
        try {
            const { data: cliente } = await axios.get(`${API}/clientes/${telefone}`)
            return msg.reply(
                `💅 Bem-vinda de volta, *${cliente.nome}*!\n\n` +
                'O que deseja fazer?\n\n' +
                '1️⃣ Ver serviços disponíveis\n' +
                '2️⃣ Agendar horário\n' +
                '3️⃣ Ver meus agendamentos\n' +
                '4️⃣ Cancelar agendamento\n' +
                '5️⃣ Ver endereço\n\n' +
                '6️⃣ Falar com o ateliê\n\n' +
                'Digite o número da opção desejada.'
            )
        } catch {
            return msg.reply(
                '💅 *Bem-vinda ao Ateliê!*\n\n' +
                'Parece que é sua primeira vez por aqui! 🌸\n\n' +
                'O que deseja fazer?\n\n' +
                '1️⃣ Ver serviços disponíveis\n' +
                '2️⃣ Agendar horário\n' +
                '3️⃣ Ver meus agendamentos\n' +
                '4️⃣ Cancelar agendamento\n' +
                '5️⃣ Ver endereço\n\n' +
                '6️⃣ Falar com o ateliê\n\n' +
                'Digite o número da opção desejada.'
            )
        }
    }

    // FLUXO DE AGENDAMENTO
    if (sessao.etapa === 'agendar_nome') {
        sessao.nome = texto
        sessao.etapa = 'agendar_servico'
        const { data } = await axios.get(`${API}/servicos`)
        let resposta = `Olá *${texto}*! 😊\n\nQual serviço deseja?\n\n`
        data.forEach(s => {
            resposta += `*${s.id}.* ${s.nome} — R$ ${s.preco}\n`
        })
        resposta += '\n\n_Digite *cancelar* a qualquer momento para voltar ao menu._'
        return msg.reply(resposta)
    }

    if (sessao.etapa === 'agendar_servico') {
        const servicoId = parseInt(texto)
        if (isNaN(servicoId)) {
            return msg.reply('❌ Digite apenas o *número* do serviço.')
        }
        sessao.servico_id = servicoId
        sessao.etapa = 'agendar_data'
        return msg.reply(
            '📅 Qual data deseja agendar?\n\n' +
            'Digite no formato: *DD/MM/AAAA*\n' +
            'Exemplo: *25/03/2026*'
        )
    }

    if (sessao.etapa === 'agendar_data') {
        try {
            const { data } = await axios.get(`${API}/horarios-disponiveis?data=${encodeURIComponent(texto)}`)

            if (data.horarios.length === 0) {
                return msg.reply(
                    '😔 Não há horários disponíveis nessa data.\n\n' +
                    'Por favor, escolha outra data:'
                )
            }

            sessao.data_escolhida = texto
            sessao.horarios_disponiveis = data.horarios
            sessao.etapa = 'agendar_horario'

            let resposta = `📅 *Horários disponíveis para ${texto}:*\n\n`
            data.horarios.forEach((h, i) => {
                resposta += `*${i + 1}.* ${h}\n`
            })
            resposta += '\nDigite o *número* do horário desejado.'
            return msg.reply(resposta)

        } catch (err) {
            const mensagem = err.response?.data?.detail || 'Data inválida.'
            return msg.reply(`❌ ${mensagem}\n\nTente novamente com outra data:`)
        }
    }

    if (sessao.etapa === 'agendar_horario') {
        const indice = parseInt(texto) - 1
        if (isNaN(indice) || indice < 0 || indice >= sessao.horarios_disponiveis.length) {
            return msg.reply('❌ Opção inválida. Digite o número do horário desejado:')
        }

        const horario = sessao.horarios_disponiveis[indice]
        const [dia, mes, ano] = sessao.data_escolhida.split('/')
        const data_hora = `${ano}-${mes}-${dia}T${horario}:00`

       try {
            await axios.post(`${API}/clientes`, { nome: sessao.nome, telefone })
            const { data: agendamento } = await axios.post(`${API}/agendamentos`, {
                telefone,
                servico_id: sessao.servico_id,
                data_hora
            })

            sessao.etapa = 'menu'

            // Avisa o ateliê. Se falhar, não afeta a confirmação da cliente
            try {
                await client.sendMessage(`${NUMERO_ATELIE}@c.us`,
                    `🔔 *Novo agendamento!*\n\n` +
                    `👤 Cliente: ${agendamento.cliente.nome}\n` +
                    `📞 Telefone: ${agendamento.cliente.telefone}\n` +
                    `✂️ Serviço: ${agendamento.servico.nome}\n` +
                    `📅 Data: ${new Date(agendamento.data_hora).toLocaleString('pt-BR')}\n` +
                    `💰 Valor: R$ ${agendamento.servico.preco}`
                )
            } catch (errWhats) {
                console.error('Aviso WhatsApp falhou (não crítico):', errWhats.message)
            }

            return msg.reply(
                '✅ *Agendamento confirmado!*\n\n' +
                `👤 Cliente: ${agendamento.cliente.nome}\n` +
                `✂️ Serviço: ${agendamento.servico.nome}\n` +
                `📅 Data: ${new Date(agendamento.data_hora).toLocaleString('pt-BR')}\n` +
                `💰 Valor: R$ ${agendamento.servico.preco}\n\n` +
                '📍 Lembrando: tolerância de atraso de 10 minutos.\n' +
                'Digite *0* para voltar ao menu.'
            )
        } catch (err) {
            const mensagem = err.response?.data?.detail || 'Erro ao agendar.'
            sessao.etapa = 'menu'
            return msg.reply(`❌ ${mensagem}\n\nDigite *0* para voltar ao menu.`)
        }
    }
    if (sessao.etapa === 'falar_com_atelie') {
        // Bot fica quieto, só mostra menu se digitar cancelar
        // (o cancelar já é tratado no início da função)
        return
    }
    if (sessao.etapa === 'cancelar_id') {
        const id = parseInt(texto)

        if (isNaN(id)) {
            return msg.reply('❌ ID inválido. Digite apenas o número do agendamento:')
        }

        // Busca o agendamento pra mostrar detalhes antes de confirmar
        try {
            const { data: agendamentos } = await axios.get(`${API}/agendamentos/${telefone}`)
            const ag = agendamentos.find(a => a.id === id)

            if (!ag) {
                sessao.etapa = 'menu'
                return msg.reply('❌ Agendamento não encontrado.\n\nDigite *0* para voltar ao menu.')
            }

            sessao.cancelar_id = id
            sessao.etapa = 'cancelar_confirmar'

            return msg.reply(
                `⚠️ *Confirmar cancelamento?*\n\n` +
                `✂️ Serviço: ${ag.servico.nome}\n` +
                `📅 Data: ${new Date(ag.data_hora).toLocaleString('pt-BR')}\n` +
                `💰 Valor: R$ ${ag.servico.preco}\n\n` +
                `Digite *sim* para confirmar ou *não* para voltar ao menu.`
            )
        } catch (err) {
            sessao.etapa = 'menu'
            return msg.reply('❌ Erro ao buscar agendamento.\n\nDigite *0* para voltar ao menu.')
        }
    }

    if (sessao.etapa === 'cancelar_confirmar') {
        if (texto.toLowerCase() === 'não' || texto.toLowerCase() === 'nao') {
            sessao.etapa = 'menu'
            return msg.reply('✅ Cancelamento abortado.\n\nDigite *0* para voltar ao menu.')
        }

        if (texto.toLowerCase() !== 'sim') {
            return msg.reply('Digite *sim* para confirmar ou *não* para cancelar:')
        }

        try {
            const { data } = await axios.patch(`${API}/agendamentos/${sessao.cancelar_id}/cancelar?telefone=${telefone}`)
            sessao.etapa = 'menu'

            if (data.taxa) {
                return msg.reply(
                    '⚠️ *Cancelamento realizado!*\n\n' +
                    'Como o cancelamento foi feito com menos de 10h de antecedência, ' +
                    'será cobrado *50%* do valor no próximo agendamento.\n\n' +
                    'Digite *0* para voltar ao menu.'
                )
            }

            return msg.reply('✅ Agendamento cancelado com sucesso!\n\nDigite *0* para voltar ao menu.')

        } catch (err) {
            sessao.etapa = 'menu'
            const mensagem = err.response?.data?.detail || 'Erro ao cancelar.'
            return msg.reply(`❌ ${mensagem}\n\nDigite *0* para voltar ao menu.`)
        }
    }
}

// Servidor interno: o agendador da API (scheduler.py) manda um POST aqui e o
// bot envia a mensagem pelo WhatsApp. Também deixa a conversa pronta para a
// resposta "sim/não" ao lembrete.
const http = require('http')

const servidor = http.createServer(async (req, res) => {
    if (req.method === 'POST') {
        let body = ''
        req.on('data', chunk => body += chunk)
        req.on('end', async () => {
            try {
                const { telefone, mensagem, agendamento_id } = JSON.parse(body)

                // Tenta enviar para @c.us primeiro, se falhar tenta @lid
                try {
                    await client.sendMessage(`55${telefone}@c.us`, mensagem)
                } catch (errCus) {
                    console.log('Falhou @c.us, tentando buscar contato...')
                    // Busca o contato pelo número
                    const contatos = await client.getContacts()
                    const contato = contatos.find(c =>
                        c.number === `55${telefone}` ||
                        c.number === telefone
                    )
                    if (contato) {
                        await contato.sendMessage(mensagem)
                    } else {
                        throw new Error(`Contato não encontrado para ${telefone}`)
                    }
                }

                // Salva o estado de confirmação na sessão
                if (agendamento_id) {
                    if (!sessoes[telefone]) sessoes[telefone] = {}
                    sessoes[telefone].etapa = 'confirmar_lembrete'
                    sessoes[telefone].confirmar_id = agendamento_id
                    await axios.post(`${API}/sessoes/${telefone}`, sessoes[telefone])
                }

                res.writeHead(200)
                res.end(JSON.stringify({ ok: true }))
            } catch (err) {
                console.error('Erro ao enviar mensagem:', err.message)
                res.writeHead(500)
                res.end(JSON.stringify({ ok: false }))
            }
        })
    } else {
        res.writeHead(405)
        res.end()
    }
})

// Escuta só em 127.0.0.1. Aberto para a rede, qualquer pessoa conseguiria
// mandar WhatsApp pelo número do ateliê.
servidor.listen(3001, '127.0.0.1', () => {
    console.log('Servidor de mensagens rodando na porta 3001')
})

client.initialize()
