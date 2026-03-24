import os
import json
import threading
import math
from flask import Flask, request, jsonify, render_template_string
from huggingface_hub import HfApi

app = Flask(__name__)

HF_TOKEN = os.environ.get("HF_TOKEN")
DATASET_ID = "Stlcx/daten"

api = HfApi()

BASE_DIR = "/data" if os.path.exists("/data") else "/tmp"
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
DB_FILE = os.path.join(BASE_DIR, "db.json")

os.makedirs(UPLOAD_DIR, exist_ok=True)

LOCK = threading.Lock()

# 🔥 SPEED CONFIG
CHUNK = 8 * 1024 * 1024      # 8MB chunks (faster)
PARALLEL = 8                # more workers = faster

SPLIT_THRESHOLD = 50 * 1024 * 1024 * 1024
SPLIT_SIZE = 500 * 1024 * 1024


def load_db():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE) as f:
        return json.load(f)

def save_db(db):
    with open(DB_FILE, "w") as f:
        json.dump(db, f)

DB = load_db()


HTML = """
<!DOCTYPE html>
<html>
<head>
<title>God Uploader</title>
<style>
body{background:#0f172a;color:white;font-family:sans-serif}
h1{text-align:center}

.section{margin:20px;padding:20px;background:#1e293b;border-radius:15px}
.drop{border:2px dashed #38bdf8;padding:40px;text-align:center;border-radius:15px}

.file{background:#0f172a;padding:12px;margin:10px 0;border-radius:10px}
.bar{height:10px;background:#334155;border-radius:5px}
.fill{height:10px;background:#22c55e;width:0%}

.dataset-file{
 background:#0f172a;
 padding:10px;
 margin:8px;
 border-radius:8px;
 border:1px solid #334155;
}
button{cursor:pointer}
</style>
</head>

<body>

<h1>🚀 GOD SPEED UPLOADER</h1>

<div class="section">
<div class="drop">
<input type="file" id="fileInput" multiple>
</div>
<div id="uploads"></div>
</div>

<div class="section">
<h2>📂 Dataset Files</h2>
<div id="files"></div>
</div>

<script>
const CHUNK = 8*1024*1024;
const PARALLEL = 8;

let db;
let canceled = {};

// ===== UTIL =====
function formatSize(bytes){
 let u=["B","KB","MB","GB","TB"];let i=0;
 while(bytes>=1024){bytes/=1024;i++;}
 return bytes.toFixed(2)+" "+u[i];
}

// ===== INDEXEDDB =====
function openDB(){
 return new Promise(res=>{
  let req=indexedDB.open("uploader",1);
  req.onupgradeneeded=e=>{
   db=e.target.result;
   db.createObjectStore("files",{keyPath:"id"});
  };
  req.onsuccess=e=>{db=e.target.result;res();}
 });
}

function saveFile(id,file){
 return new Promise(r=>{
  let tx=db.transaction("files","readwrite");
  tx.objectStore("files").put({id,file});
  tx.oncomplete=r;
 });
}

function getAllFiles(){
 return new Promise(r=>{
  let tx=db.transaction("files","readonly");
  let req=tx.objectStore("files").getAll();
  req.onsuccess=()=>r(req.result);
 });
}

function deleteFile(id){
 db.transaction("files","readwrite").objectStore("files").delete(id);
}

// ===== FILE LIST =====
async function loadFiles(){
 let res=await fetch("/files");
 let data=await res.json();

 let div=document.getElementById("files");
 div.innerHTML="";

 data.forEach(f=>{
  let box=document.createElement("div");
  box.className="dataset-file";
  box.innerText=f;
  div.appendChild(box);
 });
}

// ===== CANCEL =====
function cancelUpload(id){
 canceled[id]=true;
 fetch("/cancel/"+id);
 deleteFile(id);
 document.getElementById("txt_"+id).innerText="❌ Canceled";
}

// ===== UPLOAD =====
async function upload(file){
 let id=crypto.randomUUID();
 await saveFile(id,file);

 await fetch("/init",{
  method:"POST",
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({id,name:file.name,size:file.size})
 });

 startUpload(id,file);
}

async function startUpload(id,file){
 let status=await fetch("/status").then(r=>r.json());
 let uploaded=status[id]?.uploaded || 0;

 let total=file.size;
 let totalChunks=Math.ceil(total/CHUNK);
 let next=Math.floor(uploaded/CHUNK);

 let div=document.createElement("div");
 div.className="file";
 div.innerHTML=`
 <div style="display:flex;justify-content:space-between">
  <span>${file.name}</span>
  <button onclick="cancelUpload('${id}')">✖</button>
 </div>
 <div class="bar"><div id="bar_${id}" class="fill"></div></div>
 <div id="txt_${id}">Starting...</div>`;
 document.getElementById("uploads").appendChild(div);

 let lastTime=Date.now();
 let lastUploaded=uploaded;

 async function send(i){
  if(canceled[id]) throw "c";

  let off=i*CHUNK;
  let chunk=file.slice(off,off+CHUNK);

  let form=new FormData();
  form.append("file",chunk);
  form.append("id",id);
  form.append("offset",off);

  let r=await fetch("/upload",{method:"POST",body:form});
  let d=await r.json();
  if(!d.ok) throw "fail";

  uploaded+=chunk.size;

  let now=Date.now();
  let dt=(now-lastTime)/1000;
  let speed=(uploaded-lastUploaded)/dt;

  lastTime=now;
  lastUploaded=uploaded;

  let percent=(uploaded/total)*100;
  let eta=(total-uploaded)/(speed||1);

  document.getElementById("bar_"+id).style.width=percent+"%";
  document.getElementById("txt_"+id).innerText=
   percent.toFixed(1)+"% | "+
   formatSize(uploaded)+" / "+formatSize(total)+" | "+
   (speed/1024/1024).toFixed(2)+" MB/s | ETA "+eta.toFixed(1)+"s";
 }

 async function worker(){
  while(true){
   if(canceled[id]) return;
   let i=next++;
   if(i>=totalChunks) break;
   try{await send(i);}catch{next--;}
  }
 }

 await Promise.all(Array(PARALLEL).fill().map(worker));

 if(canceled[id]) return;

 document.getElementById("txt_"+id).innerText="Finalizing...";
 await fetch("/complete/"+id);

 deleteFile(id);
 document.getElementById("txt_"+id).innerText="✅ DONE";
 loadFiles();
}

// ===== RESUME =====
async function resume(){
 let files=await getAllFiles();
 for(let f of files) startUpload(f.id,f.file);
}

// ===== INIT =====
document.getElementById("fileInput").onchange=e=>{
 for(let f of e.target.files) upload(f);
};

(async ()=>{
 await openDB();
 await resume();
 await loadFiles();
 setInterval(loadFiles,10000);
})();
</script>

</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/status")
def status():
    return jsonify(DB)

@app.route("/init", methods=["POST"])
def init():
    d = request.json
    DB[d["id"]] = {"name": d["name"], "size": d["size"], "uploaded": 0, "cancel": False}
    save_db(DB)
    return jsonify(ok=True)

@app.route("/upload", methods=["POST"])
def upload():
    f = request.files["file"]
    uid = request.form["id"]
    offset = int(request.form["offset"])

    with LOCK:
        if uid not in DB or DB[uid]["cancel"]:
            return jsonify(ok=False)

        path = os.path.join(UPLOAD_DIR, uid)

        with open(path, "r+b" if os.path.exists(path) else "wb") as file:
            file.seek(offset)
            data = f.read()
            file.write(data)

        DB[uid]["uploaded"] += len(data)
        save_db(DB)

    return jsonify(ok=True)

@app.route("/complete/<uid>")
def complete(uid):
    if uid not in DB:
        return jsonify(error="missing")

    path = os.path.join(UPLOAD_DIR, uid)
    name = DB[uid]["name"]

    size = os.path.getsize(path)

    if size < SPLIT_THRESHOLD:
        with open(path, "rb") as f:
            api.upload_file(path_or_fileobj=f,
                path_in_repo=name,
                repo_id=DATASET_ID,
                repo_type="dataset",
                token=HF_TOKEN)
    else:
        parts = math.ceil(size / SPLIT_SIZE)
        with open(path, "rb") as f:
            for i in range(parts):
                chunk = f.read(SPLIT_SIZE)
                api.upload_file(path_or_fileobj=chunk,
                    path_in_repo=f"{name}.part{i}",
                    repo_id=DATASET_ID,
                    repo_type="dataset",
                    token=HF_TOKEN)

    os.remove(path)
    del DB[uid]
    save_db(DB)

    return jsonify(done=True)

@app.route("/cancel/<uid>")
def cancel(uid):
    if uid in DB:
        DB[uid]["cancel"] = True
        save_db(DB)
    return jsonify(canceled=True)

@app.route("/files")
def files():
    try:
        return jsonify(api.list_repo_files(
            repo_id=DATASET_ID,
            repo_type="dataset",
            token=HF_TOKEN))
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7860)
