import frappe
import json
import requests

# 🔐 CONFIG (UPDATE THESE)
VERIFY_TOKEN = "my_test_token_123"
ACCESS_TOKEN = "EAANJvmmNUBMBRA47nofzSRL4BfGyOdmXoQfk5HCZCNCOybWEZCz2Pn0iZBUZAH032tGrKj1VVWujCBZB62bcLgvZCZCwoStHtz9DO0xrtNCsPXDa7v79jatYR2WnZANuxTEt9xzZA5X3M6AHrFY1ZCjUg1ZCc2UBgOURPA4cIZBMTg50g391so5NPxTGxn4O9Pe4aqDH9qWXxp557iu1XkbGssMpohqCMwZBJW0KmAutZALVl6JlifVWiTlRsIK7w0GkTD7cLGLrTct5ApV7PaQvjjKrBO"
PHONE_NUMBER_ID = "1078295112026940"


# ─────────────────────────────────────
# 🌐 WEBHOOK (META ENTRY POINT)
# ─────────────────────────────────────
@frappe.whitelist(allow_guest=True)
def webhook():

    # ✅ META VERIFICATION
    if frappe.request.method == "GET":
        verify_token = frappe.request.args.get("hub.verify_token")
        challenge = frappe.request.args.get("hub.challenge")

        if verify_token == VERIFY_TOKEN:
            return challenge
        return "Verification failed"

    # ✅ RECEIVE MESSAGE
    if frappe.request.method == "POST":
        data = json.loads(frappe.request.data)

        try:
            value = data["entry"][0]["changes"][0]["value"]
            messages = value.get("messages", [])

            if messages:
                msg = messages[0]
                phone = msg["from"]
                text = msg.get("text", {}).get("body", "").strip()

                frappe.logger().info(f"Incoming: {phone} - {text}")

                # 🤖 Process chatbot
                reply = process_chatbot(phone, text)

                # 📤 Send reply
                send_whatsapp_message(phone, reply)

        except Exception as e:
            frappe.log_error(str(e), "WhatsApp Error")

        return "OK"


# ─────────────────────────────────────
# 🤖 CHATBOT ENGINE
# ─────────────────────────────────────
def process_chatbot(phone, text):

    phone = normalize_phone(phone)
    session = get_session(phone)
    text_lower = text.lower()

    # 🟢 START / RESET
    if text_lower in ["hi", "hello", "start"]:
        session.status = "MENU"
        session.cart = ""
        session.save(ignore_permissions=True)

        return "👋 Welcome!\n\n🛍 Available Items:\n- TSHIRT\n- JEANS\n\nType item name to order"

    # 🔹 MENU (SELECT ITEM)
    if session.status in ["NEW", "MENU"]:

        item = detect_item(text_lower)

        if not item:
            return "❌ Please choose: TSHIRT or JEANS"

        session.cart = json.dumps([{"item_code": item}])
        session.status = "QTY"
        session.save(ignore_permissions=True)

        return f"How many {item}?"

    # 🔹 QUANTITY
    elif session.status == "QTY":

        try:
            qty = int(text)
        except:
            return "❌ Enter valid quantity (number)"

        cart = json.loads(session.cart)
        cart[0]["qty"] = qty

        session.cart = json.dumps(cart)
        session.status = "CONFIRM"
        session.save(ignore_permissions=True)

        return f"🛒 Confirm order?\n{qty} x {cart[0]['item_code']}\n\nReply YES or NO"

    # 🔹 CONFIRMATION
    elif session.status == "CONFIRM":

        if text_lower not in ["yes", "y"]:
            session.status = "MENU"
            session.save(ignore_permissions=True)
            return "❌ Order cancelled. Start again (type item name)."

        session.status = "ADDRESS"
        session.save(ignore_permissions=True)

        return "📍 Please send delivery address"

    # 🔹 ADDRESS + CREATE ORDER
    elif session.status == "ADDRESS":

        address = text
        cart = json.loads(session.cart)

        customer = get_customer(phone)

        # 🧾 Create Sales Order
        so = frappe.get_doc({
            "doctype": "Sales Order",
            "customer": customer,
            "items": cart
        })

        so.insert(ignore_permissions=True)
        so.submit()

        session.status = "DONE"
        session.cart = ""
        session.save(ignore_permissions=True)

        return f"✅ Order Confirmed!\nSales Order: {so.name}"

    # 🔹 DONE → Restart
    elif session.status == "DONE":
        session.status = "MENU"
        session.save(ignore_permissions=True)

        return "🙏 Thank you!\n\nType item name to order again."

    return "Send 'Hi' to start"


# ─────────────────────────────────────
# 🧩 HELPERS
# ─────────────────────────────────────
def get_session(phone):

    name = frappe.db.get_value("WhatsApp Session", {"phone": phone})

    if name:
        return frappe.get_doc("WhatsApp Session", name)

    doc = frappe.get_doc({
        "doctype": "WhatsApp Session",
        "phone": phone,
        "status": "NEW",
        "cart": ""
    })
    doc.insert(ignore_permissions=True)
    return doc


def detect_item(text):

    if "tshirt" in text or "shirt" in text:
        return "TSHIRT"

    if "jeans" in text:
        return "JEANS"

    return None


def get_customer(phone):

    # 🔍 match last 10 digits
    data = frappe.db.sql("""
        SELECT name FROM `tabCustomer`
        WHERE REPLACE(mobile_no, '+', '') LIKE %s
        LIMIT 1
    """, (f"%{phone[-10:]}",), as_dict=True)

    if data:
        return data[0].name

    # ➕ create new customer
    doc = frappe.get_doc({
        "doctype": "Customer",
        "customer_name": f"Customer {phone}",
        "mobile_no": phone
    })
    doc.insert(ignore_permissions=True)
    return doc.name


def normalize_phone(phone):
    return phone.replace("+", "").replace(" ", "").strip()


# ─────────────────────────────────────
# 📤 SEND WHATSAPP MESSAGE
# ─────────────────────────────────────
def send_whatsapp_message(to, message):

    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": message
        }
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        frappe.logger().info(f"WhatsApp Sent: {response.text}")
    except Exception as e:
        frappe.log_error(str(e), "WhatsApp Send Error")