import streamlit as st
import pandas as pd
from pathlib import Path

st.set_page_config(page_title="Resell AI", page_icon="🤖", layout="wide")
DATA = Path("products.csv")

def load_products():
    df = pd.read_csv(DATA)
    for c in ["cost","shipping","stock"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df

def sale_price(cost, shipping, fee=0.13, target=0.25):
    return round((cost + shipping) / max(0.01, 1-fee-target), 2)

def make_description(r, price):
    return f"""**{r.title}**

Produit neuf.
Stock disponible : {int(r.stock)}
Prix conseillé : {price:.2f} €

Référence : {r.sku}

Vérifie les conditions de livraison, disponibilité et retours avant publication."""

st.title("🤖 Resell AI — MVP gratuit")
st.caption("Sourcing → analyse → annonce → commande")

df = load_products()

with st.sidebar:
    st.header("Paramètres")
    fee = st.slider("Commission estimée (%)", 0.0, 30.0, 13.0, 0.5)/100
    target = st.slider("Marge cible (%)", 5.0, 60.0, 25.0, 1.0)/100
    st.divider()
    st.write("eBay : prêt pour une future connexion API")
    st.write("Vinted/Leboncoin : brouillons uniquement")

rows=[]
for _,r in df.iterrows():
    price=sale_price(r.cost,r.shipping,fee,target)
    commission=price*fee
    profit=price-r.cost-r.shipping-commission
    margin=profit/price if price else 0
    score=(30 if r.stock>0 else 0)+(40 if margin>=target else 0)+(20 if profit>=5 else 0)+(10 if price<=100 else 0)
    rows.append([r.sku,r.title,r.cost,r.shipping,price,profit,margin*100,r.stock,score])

analysis=pd.DataFrame(rows,columns=["SKU","Produit","Coût","Livraison","Prix conseillé","Profit estimé","Marge %","Stock","Score"])
analysis=analysis.sort_values(["Score","Profit estimé"],ascending=False)

c1,c2,c3=st.columns(3)
c1.metric("Produits",len(analysis))
c2.metric("En stock",int((analysis.Stock>0).sum()))
c3.metric("Profit moyen",f"{analysis['Profit estimé'].mean():.2f} €")

st.subheader("Produits analysés")
st.dataframe(analysis,use_container_width=True,hide_index=True)

st.subheader("Générateur d'annonce")
sku=st.selectbox("Produit",analysis.SKU.astype(str).tolist())
r=df[df.sku.astype(str)==str(sku)].iloc[0]
price=sale_price(r.cost,r.shipping,fee,target)
title=st.text_input("Titre",str(r.title)[:80])
description=st.text_area("Description",make_description(r,price),height=180)
price=st.number_input("Prix",value=float(price),step=0.01)

if st.button("Ajouter aux brouillons",type="primary"):
    p=Path("draft_listings.csv")
    new=pd.DataFrame([{"sku":r.sku,"title":title,"price":price,"description":description,"source_url":r.source_url,"status":"DRAFT"}])
    if p.exists():
        new=pd.concat([pd.read_csv(p),new],ignore_index=True).drop_duplicates("sku",keep="last")
    new.to_csv(p,index=False)
    st.success("Annonce ajoutée aux brouillons.")

st.subheader("File de commandes")
st.info("La version connectée recevra les commandes d'une marketplace via son API/webhook puis préparera l'expédition. La transmission automatique au fournisseur nécessite une intégration autorisée.")
with st.form("order"):
    o_sku=st.text_input("SKU")
    name=st.text_input("Nom du destinataire")
    address=st.text_input("Adresse")
    postal=st.text_input("Code postal")
    city=st.text_input("Ville")
    ok=st.form_submit_button("Créer la commande")
    if ok and o_sku and address:
        p=Path("orders.csv")
        new=pd.DataFrame([{"sku":o_sku,"buyer_name":name,"address":address,"postal":postal,"city":city,"status":"READY_FOR_FULFILLMENT"}])
        if p.exists(): new=pd.concat([pd.read_csv(p),new],ignore_index=True)
        new.to_csv(p,index=False)
        st.success("Commande créée.")

st.caption("Prototype local : aucune donnée n'est envoyée à un service externe.")
