# Généralités sur les fonctions numériques

**Pr. Abdelmounaim Elhadi**

> Cours — transcription en Markdown + LaTeX à partir du PDF fourni.

## 1. Fonction majorée, fonction minorée, fonction bornée

### Activité 1

On considère la fonction \(f\) définie par :

\[
f(x)=\frac{2x^2+3}{x^2+1}.
\]

1. Déterminer \(D_f\), l’ensemble de définition de \(f\).
2. Montrer que \(\forall x\in D_f,\ f(x)\leq 3\). On dit alors que \(f\) est majorée par \(3\) sur \(D_f\).
3. Montrer que \(\forall x\in D_f,\ f(x)\geq 2\). On dit alors que \(f\) est minorée par \(2\) sur \(D_f\).
4. En déduire que \(\forall x\in D_f,\ 2\leq f(x)\leq 3\). On dit alors que \(f\) est bornée sur \(D_f\).

### Définition

Soit \(f\) une fonction définie sur un intervalle \(I\). On dit que :

- \(f\) est **majorée** sur \(I\) s’il existe un réel \(M\) tel que \(\forall x\in I,\ f(x)\leq M\) ;
- \(f\) est **minorée** sur \(I\) s’il existe un réel \(m\) tel que \(\forall x\in I,\ m\leq f(x)\) ;
- \(f\) est **bornée** sur \(I\) s’il existe des réels \(m\) et \(M\) tels que \(\forall x\in I,\ m\leq f(x)\leq M\).

### Exemple

On considère \(f:x\mapsto 1-\frac1x\).

- \(f\) est majorée sur \(]0,+\infty[\) par \(1\), car \(\forall x\in]0,+\infty[,\ f(x)-1=-\frac1x<0\).
- \(f\) est minorée sur \(]-\infty,0[\) par \(1\), car \(\forall x\in]-\infty,0[,\ f(x)-1=-\frac1x>0\).

### Interprétation graphique

Soit \(f\) une fonction définie sur un intervalle \(I\) de \(\mathbb R\), et soit \((C_f)\) sa courbe.

- Si \(f\) est majorée par un réel \(M\) sur \(I\), alors \((C_f)\) est au-dessous de la droite d’équation \(y=M\) sur \(I\).
- Si \(f\) est minorée par un réel \(m\) sur \(I\), alors \((C_f)\) est au-dessus de la droite d’équation \(y=m\) sur \(I\).

### Application 1

On considère les fonctions \(f\) et \(g\) définies respectivement par :

\[
f(x)=3-\sqrt{1-2x},\qquad g(x)=\sqrt{x^2+4}.
\]

1. Déterminer \(D_f\) et \(D_g\).
2. Montrer que \(f\) est majorée par \(3\) sur \(D_f\).
3. Montrer que \(g\) est minorée par \(2\) sur \(D_g\).

### Extremum

Soit \(f\) une fonction définie sur un intervalle \(I\), et soit \(a\in I\). On dit que :

- \(f(a)\) est la **valeur minimale** (ou le minimum) de \(f\) sur \(I\) si \(\forall x\in I,\ f(x)\geq f(a)\) ;
- \(f(a)\) est la **valeur maximale** (ou le maximum) de \(f\) sur \(I\) si \(\forall x\in I,\ f(x)\leq f(a)\) ;
- \(f(a)\) est un **extremum** de \(f\) sur \(I\) s’il est le maximum ou le minimum de \(f\) sur \(I\).

### Exemple

\(-3\) est la valeur minimale de \(f:x\mapsto x^2-4x+1\) sur \(\mathbb R\). En effet,

\[
f(x)-(-3)=(x-2)^2\geq 0,\qquad \forall x\in\mathbb R,
\]

et \(f(2)=-3\).

### Exercice 2 de la série

Soit \(f\) la fonction numérique définie par :

\[
f(x)=x+\frac4x.
\]

1. Déterminer \(D_f\).
2. (a) Calculer \(f(2)\).  
   (b) Montrer que \(f\) est minorée par \(4\) sur \(]0,+\infty[\). Conclure.
3. Montrer que \(-4\) est la valeur maximale de \(f\) sur \(]-\infty,0[\).

## 2. Fonctions périodiques

### Activité 2

La figure du cours représente la courbe d’une fonction définie sur \(\mathbb R\).

1. Vérifier que \(f(-2)=f(2)\), \(f(0)=f(4)\) et \(f(1)=f(5)\).
2. Soit \(x\in\mathbb R\). Déterminer la relation entre \(f(x+4)\) et \(f(x)\).

### Fonction périodique

Soit \(f\) une fonction définie sur \(D\), et soit \(T>0\). On dit que \(f\) est périodique (ou \(T\)-périodique) sur \(D\) si :

- \(x+T\in D\) pour tout \(x\in D\) ;
- \(f(x+T)=f(x)\) pour tout \(x\in D\).

### Exemple

- Les fonctions \(x\mapsto\sin x\) et \(x\mapsto\cos x\) sont périodiques de période \(2\pi\).
- La fonction \(x\mapsto\tan x\) est périodique de période \(\pi\).

### Application 2

On considère les fonctions \(f\) et \(g\) définies sur \(\mathbb R\) par :

\[
f(x)=\cos^2 x,\qquad g(x)=\sin(2\pi x).
\]

Montrer que \(f\) et \(g\) sont périodiques de périodes respectives \(\pi\) et \(1\).

## 3. Comparaison de deux fonctions

### Définition

Soient \(f\) et \(g\) deux fonctions définies sur le même ensemble \(D\). On dit que :

- \(f\) et \(g\) sont égales sur \(D\) si et seulement si \(\forall x\in D,\ f(x)=g(x)\) ;
- \(f\) est supérieure ou égale à \(g\) sur \(D\) si et seulement si \(\forall x\in D,\ f(x)\geq g(x)\), et l’on écrit \(f\geq g\).

### Exemple

Soient \(f\) et \(g\) définies sur \(\mathbb R^*\) par :

\[
f(x)=x+1+\frac1{x^2+2},\qquad g(x)=x+1.
\]

Pour tout \(x\in\mathbb R^*\),

\[
f(x)-g(x)=\frac1{x^2+2}>0.
\]

Donc \(f>g\) sur \(\mathbb R^*\).

### Interprétation graphique

Soient \(f\) et \(g\) deux fonctions et \(D\subseteq D_f\cap D_g\).

- Si \(f>g\) sur \(D\), alors \((C_f)\) est strictement au-dessus de \((C_g)\) sur \(D\).
- Si \(f\leq g\) sur \(D\), alors \((C_f)\) est au-dessous de \((C_g)\) sur \(D\).

### Application 3

On considère \(f\) et \(g\) définies sur \(\mathbb R\) par :

\[
f(x)=x^2-2x+1,\qquad g(x)=-2x^2+4x+1.
\]

1. Étudier le signe de \(f(x)-g(x)\) sur \(\mathbb R\).
2. En déduire une comparaison entre \(f\) et \(g\) sur \(\mathbb R\).

### Exercice 3 de la série

Soient \(f\) et \(g\) deux fonctions de courbes représentées dans le document source.

1. Résoudre graphiquement les équations \(f(x)=2\), \(f(x)=0\) et \(f(x)=g(x)\).
2. Résoudre graphiquement les inéquations \(f(x)<2\), \(g(x)\geq0\) et \(f(x)>g(x)\).

## 4. Image d’un intervalle par une fonction numérique

### Définition

Soit \(f\) une fonction définie sur un intervalle \(I\). L’ensemble des valeurs \(f(x)\) telles que \(x\in I\) est appelé **image de l’intervalle \(I\) par \(f\)**, et se note \(f(I)\) :

\[
f(I)=\{f(x)\mid x\in I\}.
\]

### Exemple

La courbe du document source est celle d’une fonction \(f\) définie sur \([-2,4]\). Les images indiquées sont :

\[
\begin{aligned}
f([-2,-1])&=[0,2],\\
f([0,1])&=[0,2],\\
f([1,3])&=[-1,2],\\
f([1,4])&=[-1,2],\\
f([-1,1])&=[0,2],\\
f([0,3])&=[-1,2],\\
f([-2,4])&=[-1,2].
\end{aligned}
\]

### Technique

Soit \(f\) une fonction définie sur un intervalle \([a,b]\).

- Si \(f\) est croissante sur \([a,b]\), alors \(f([a,b])=[f(a),f(b)]\).
- Si \(f\) est décroissante sur \([a,b]\), alors \(f([a,b])=[f(b),f(a)]\).
- Si \(f\) change de monotonie sur \([a,b]\), alors \(f([a,b])=[m,M]\), où \(m\) est le minimum et \(M\) le maximum de \(f\) sur \([a,b]\).

### Exercice 1 de la série

Le cours donne un tableau de variations. Déterminer :

\[
f([-4,0]),\quad f([0,1]),\quad f([0,2]),\quad
f([-4,1]),\quad f([1,+\infty[).
\]

## 5. Monotonie d’une fonction numérique

### Activité 3

On considère la fonction \(f\) définie par :

\[
f(x)=\frac1{x^2+1}.
\]

1. Déterminer \(D_f\).
2. Étudier la parité de \(f\), puis interpréter graphiquement le résultat.
3. Étudier la monotonie de \(f\) sur \([0,+\infty[\), puis sur \(]-\infty,0]\).
4. Étudier la monotonie de \(3f\), \(-2f\) et \(f+3\) sur \([0,+\infty[\).

### Propriété

Soit \(f\) une fonction numérique définie sur un intervalle \(I\), \(k\in\mathbb R\) et \(\lambda\in\mathbb R^*\).

- Les fonctions \(f\) et \(f+k\) ont le même sens de variation sur \(I\).
- Si \(\lambda>0\), alors \(f\) et \(\lambda f\) ont le même sens de variation sur \(I\).
- Si \(\lambda<0\), alors \(f\) et \(\lambda f\) ont des sens de variation contraires sur \(I\).

### Application 4

Soit \(f\) une fonction définie sur \([-3,3]\) par la courbe du document source. Donner les tableaux de variations de \(f\), de \(f+2\) et de \(-3f\).

## 6. Composée de deux fonctions numériques

### Activité 4

On considère \(f\) et \(g\) définies par :

\[
f(x)=-x+5,\qquad g(x)=\sqrt{x}.
\]

1. (a) Calculer \(f(1)\), puis \(g(f(1))\).  
   (b) Calculer \(f(-4)\), puis \(g(f(-4))\).  
   (c) Calculer \(f(8)\). Peut-on calculer \(g(f(8))\)?
2. (a) Déterminer l’intervalle \(I\) tel que \(g(f(x))\) soit calculable pour tout \(x\in I\).  
   (b) Déterminer l’expression de \(g(f(x))\) pour tout \(x\in I\).

### Fonction composée

Soient \(g\) une fonction définie sur un intervalle \(J\) et \(f\) une fonction définie sur un intervalle \(I\), telle que, pour tout \(x\in I\), \(f(x)\in J\). La fonction composée de \(f\) suivie de \(g\), notée \(g\circ f\), est définie par :

\[
(g\circ f)(x)=g(f(x)).
\]

### Remarque

\[
x\in D_{g\circ f}\iff x\in D_f\ \text{et}\ f(x)\in D_g.
\]

En général, \(g\circ f\neq f\circ g\).

### Exemple

Soient \(f:x\mapsto x^2\), définie sur \(D_f=\mathbb R\), et

\[
g:x\mapsto\frac{2x}{x-4},\qquad D_g=\mathbb R\setminus\{4\}.
\]

Le domaine de \(g\circ f\) vérifie :

\[
\begin{aligned}
x\in D_{g\circ f}
&\iff x\in D_f\ \text{et}\ f(x)\in D_g\\
&\iff x\in\mathbb R\ \text{et}\ x^2\neq4\\
&\iff x\in\mathbb R,\ x\neq-2,\ x\neq2.
\end{aligned}
\]

Donc :

\[
D_{g\circ f}=]-\infty,-2[\ \cup\ ]2,+\infty[.
\]

Pour tout \(x\in D_{g\circ f}\),

\[
(g\circ f)(x)=g(x^2)=\frac{2x^2}{x^2-4}.
\]

### Application 5

1. Soient \(f(x)=\frac1x\) et \(g(x)=\frac{2x+3}{3x-6}\).
   - (a) Déterminer \(D_f\), \(D_g\) et \(D_{g\circ f}\).
   - (b) Donner l’expression de \(g\circ f\).
2. Écrire la fonction \(h\), définie sur \(\mathbb R_+\) par
   \[
   h(x)=\frac{\sqrt{x-2}}{\sqrt{x+5}},
   \]
   comme composée de deux fonctions.

### Sens de variation d’une composée

Soient \(f\) et \(g\) définies respectivement sur les intervalles \(I\) et \(J\), tels que \(f(I)\subseteq J\).

- Si \(f\) et \(g\) ont le même sens de variation, respectivement sur \(I\) et \(J\), alors \(g\circ f\) est croissante sur \(I\).
- Si \(f\) et \(g\) ont des sens de variation contraires, respectivement sur \(I\) et \(J\), alors \(g\circ f\) est décroissante sur \(I\).

### Exemple

La fonction du cours est écrite comme composée de deux fonctions :

\[
h(x)=\frac{1-x^2}{1+x^2},\qquad h=g\circ f,
\]

avec \(f:x\mapsto x^2\) et \(g:x\mapsto\frac{1-x}{1+x}\).

- \(f\) est décroissante sur \(]-\infty,0]\) et \(f(]-\infty,0])=[0,+\infty[\). Comme \(g\) est décroissante sur \([0,+\infty[\), \(h\) est croissante sur \(]-\infty,0]\).
- \(f\) est croissante sur \([0,+\infty[\) et \(f([0,+\infty[)=[0,+\infty[\). Comme \(g\) est décroissante sur \([0,+\infty[\), \(h\) est décroissante sur \([0,+\infty[\).

### Application 6

On considère \(f(x)=x^2-2x+1\) et \(g(x)=-2x+1\), définies sur \(\mathbb R\).

1. Dresser les tableaux de variations de \(f\) et de \(g\).
2. Déterminer \(f(]-\infty,1])\) et \(f([1,+\infty[)\).
3. Étudier les variations de \(g\circ f\) sur \(]-\infty,1]\) et sur \([1,+\infty[\).

### Exercice 5 de la série

On considère :

\[
f(x)=x^2-2x-1,\qquad g(x)=\frac{x-2}{x+2}.
\]

1. Donner \(D_f\), \(D_g\) et \(D_{g\circ f}\).
2. Déterminer \((g\circ f)(x)\) pour tout \(x\in D_{g\circ f}\).
3. Dresser les tableaux de variations de \(f\) et de \(g\).
4. Déterminer \(f(]-\infty,1])\) et \(f([1,+\infty[)\).
5. Étudier les variations de \(g\circ f\) sur \(]-\infty,1]\) et sur \([1,+\infty[\).

## 7. Représentation graphique de certaines fonctions

### 7.1. La fonction \(x\mapsto ax^3\)

Soit \(a\in\mathbb R^*\) et \(f:x\mapsto ax^3\). Pour tout \(x\in\mathbb R\),

\[
f(-x)=a(-x)^3=-ax^3=-f(x).
\]

Ainsi, \(f\) est impaire : il suffit de l’étudier sur \(\mathbb R_+\).

Soient \(x,y\in[0,+\infty[\) tels que \(x<y\).

- Si \(a>0\), alors \(x<y\Rightarrow x^3<y^3\Rightarrow ax^3<ay^3\). Donc \(f\) est croissante sur \([0,+\infty[\). Comme elle est impaire, elle est aussi croissante sur \(]-\infty,0]\), donc sur \(\mathbb R\).
- Si \(a<0\), alors \(x<y\Rightarrow x^3<y^3\Rightarrow ax^3>ay^3\). Donc \(f\) est décroissante sur \([0,+\infty[\). Comme elle est impaire, elle est aussi décroissante sur \(]-\infty,0]\), donc sur \(\mathbb R\).

### 7.2. La fonction \(x\mapsto\sqrt{x+a}\)

Soit \(a\in\mathbb R\) et \(f:x\mapsto\sqrt{x+a}\). Son domaine de définition est :

\[
D_f=[-a,+\infty[.
\]

Soient \(x,y\in D_f\) tels que \(x<y\). Alors :

\[
x<y\Rightarrow x+a<y+a\Rightarrow
\sqrt{x+a}<\sqrt{y+a}.
\]

Donc \(f\) est strictement croissante sur \([-a,+\infty[\).

### Application 7

On considère \(f(x)=\sqrt{x+2}\) et \(g(x)=-x^3\), de courbes \((C_f)\) et \((C_g)\) dans un repère \((O;\vec i,\vec j)\).

1. Étudier les variations de \(f\) et de \(g\).
2. Construire \((C_f)\) et \((C_g)\).
3. Résoudre graphiquement l’inéquation
   \[
   \sqrt{x+2}+x^3<0
   \]
   sur \([-2,+\infty[\).

### Exercice de la série

Soient \(f(x)=x^2-x\) et \(g(x)=\sqrt{x+2}\), de courbes \((C_f)\) et \((C_g)\) dans un repère orthonormé.

1. (a) Déterminer \(D_g\), puis vérifier que \(f(2)=g(2)\).  
   (b) Représenter \((C_f)\) et \((C_g)\).  
   (c) Déterminer graphiquement \(f^{-1}([1/2])\).  
   (d) Résoudre graphiquement, sur \([-2,+\infty[\), l’inéquation
   \[
   x^2-x-\sqrt{x+2}\leq0.
   \]
2. On considère \(h\) définie sur \(\mathbb R\) par \(h(x)=x^2-x+2\).
   - (a) Vérifier que, pour tout \(x\in\mathbb R\), \(h(x)=(g\circ f)(x)\).
   - (b) Déterminer les variations de \(h\) sur \(]-\infty,\frac12]\) et sur \([\frac12,+\infty[\) à l’aide des variations de \(f\) et de \(g\).

---

## Note de transcription

Les figures, courbes et tableaux graphiques du PDF ne sont pas recréés dans ce fichier Markdown. Les questions qui dépendent de ces éléments sont signalées comme provenant du document source. Quelques expressions ont été retranscrites à partir du texte extrait du PDF ; vérifiez-les avec les figures originales avant publication.
