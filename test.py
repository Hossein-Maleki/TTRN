from rubpy.bot import BotClient

TOKEN = "توکن"

app = BotClient(TOKEN)

@app.on_message()
async def handler(client, message):
    print("MESSAGE RECEIVED")
    await client.send_message(message.object_guid, "سلام")

app.run()

