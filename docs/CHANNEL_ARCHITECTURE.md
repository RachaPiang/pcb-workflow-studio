# ช่องทางการใช้งาน: Local UI, Discord, Telegram และ OpenClaw

ตัวแอปปัจจุบันคือ core workflow ที่ทำงานบนเครื่อง: schema, Agent, Orchestrator, approval gate, versioning และ file evidence อยู่ใน `pcb_assistant/` ส่วนหน้าเว็บเป็นเพียง client หนึ่งแบบ การเลือกเว็บใน MVP เป็นวิธีทดสอบ workflow ให้เห็นง่ายและมี upload/review ที่ครบ

ภาพที่เหมาะกับระบบระยะยาวคือ:

```text
Discord bot ─┐
Telegram bot ├─ Channel adapter / identity + command parsing ─┐
OpenClaw ────┘                                               │
Local Web UI ────────────────────────────────────────────────┤
                                                               ↓
             PCB Workflow API + Main Orchestrator
             SQLite + original files + approval gates
```

## หน้าที่ของแต่ละชั้น

**Channel adapter** รับข้อความ, project id, ผู้ใช้ และไฟล์จากช่องทางนั้น แล้วเปลี่ยนเป็นคำขอ API ที่ชัดเจน เช่น `create project`, `answer requirements`, `run plan`, `show findings`, `approve gate` ไม่ควรใส่ logic การเลือก IC หรือ logic อนุมัติไว้ใน bot

**Orchestrator** เป็นแหล่งจริงเพียงจุดเดียว Agent ทุกตัวต้องผ่าน schema, deterministic review และ human approval เหมือนกัน ไม่ว่าจะสั่งจากเว็บ, Discord, Telegram หรือ OpenClaw

**OpenClaw** เหมาะเป็น automation/gateway layer ในอนาคต เช่น รับ event จาก Discord/Telegram, เรียก skill ที่ห่อ API ของ PCB Workflow, ส่งผลลัพธ์กลับช่องทาง และตั้ง trigger ให้แจ้งเมื่อมี finding ใหม่ โดย OpenClaw ไม่ควรถือ approval token หรือแก้ SQLite ตรง ๆ

## ลำดับการทำงานของบอต

1. `/pcb new` สร้าง project และส่งคำถามที่ยังขาดเป็นข้อความสั้น ๆ
2. `/pcb answer <project> key=value` บันทึก Requirements พร้อม optimistic version
3. `/pcb approve requirements` ส่งผู้ใช้ไปหน้า approval หรือใช้ข้อความยืนยันที่มี evidence hash, reviewer และเหตุผลครบ
4. `/pcb run plan` สั่ง Agent ตามลำดับและส่งสรุป findings พร้อมลิงก์ local UI
5. `/pcb evidence` แสดง facts ที่ยัง Inferred และปุ่ม/คำสั่งให้ผู้ใช้ยืนยันจากเอกสารต้นฉบับ
6. `/pcb upload` นำเข้า PDF/BOM/netlist/DRC โดย channel adapter ต้องเก็บ original bytes ผ่าน API เท่านั้น
7. `/pcb status` แสดง Gate, blockers และ version ปัจจุบัน

การอนุมัติผ่านแชตควรใช้ได้เฉพาะเมื่อผู้ใช้ระบุ project, gate, evidence hash, ชื่อผู้อนุมัติ และเหตุผลตรงกัน หากเป็นการอ่านข้อความธรรมดา เช่น “ดูดี” หรือ “ไปต่อ” ต้องไม่ถือว่าเป็น approval

## ความปลอดภัยของช่องทาง

- map Discord user ID / Telegram user ID / OpenClaw identity ไปเป็น local reviewer identity แบบ allowlist; ห้ามเชื่อชื่อที่พิมพ์ในข้อความอย่างเดียว
- จำกัด project ที่แต่ละ identity เข้าถึงได้ และตรวจทุก mutation ด้วย version
- ไม่ส่ง datasheet ทั้งฉบับกลับเข้า channel โดยอัตโนมัติ; ส่งเฉพาะ excerpt ที่ผู้ใช้ร้องขอและเตือนว่าเป็นหลักฐานที่ต้องตรวจ
- ไฟล์จาก bot ต้องใช้ upload endpoint เดียวกับเว็บ ซึ่งตรวจขนาด, filename, zip path, hash และ parser limitations
- channel adapter ไม่ควร log API key, Codex token, PDF เนื้อหาเต็ม หรือข้อมูลที่ผู้ใช้ไม่ได้ขอ
- Approval และ release ยังต้องบันทึกใน SQLite พร้อม hash; การส่งข้อความสำเร็จไม่ใช่หลักฐานว่า Gate ผ่าน

## แผนเพิ่มระบบทีละเฟส

1. ทำ `service.py` facade รอบ Orchestrator ให้มีเมธอด command ที่ channel adapters ใช้ร่วมกัน
2. เพิ่ม Telegram adapter แบบ long polling สำหรับ local-only test โดยเก็บ bot token ใน environment และ allowlist chat/user IDs
3. เพิ่ม Discord adapter แบบ slash commands และ interaction responses; ใช้ attachment URL อ่านผ่าน adapter แล้วส่ง bytes เข้า API
4. เพิ่ม OpenClaw skill/MCP wrapper ที่เรียก facade เดิม และกำหนด approval เป็น explicit action
5. เพิ่ม queue/background jobs สำหรับงาน PDF/AI ที่นาน และส่ง job status กลับ channel
6. เพิ่ม integration tests ที่ mock Discord/Telegram/OpenClaw transport แต่ใช้ approval engine จริง

ดังนั้นไม่ต้องย้าย Agent ไปอยู่ใน Discord หรือ Telegram โดยตรง: เราจะเปลี่ยน “ช่องทางคุย” ได้ โดยรักษา core PCB workflow เดิมไว้ครบ
