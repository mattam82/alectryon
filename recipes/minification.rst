============================
 Generating external movies
============================

Alectryon normally produces plain HTML files.  For very large proofs, these files can get quite large (sometimes hundreds of megabytes), but they also tend to be highly redundant; hence, Alectryon also has the ability to generate “minified” HTML files, which contain special pointers (“backreferences”) to previous parts of the document.  These backreferences are resolved dynamically when the page is displayed in a web browser.

Here is an example proof, written in a way that generates lots of redundant objects (for example, section variables appear in the proof context at every step of the proof):

.. coq::

   Require Import List.
   Import ListNotations.

   Section Folds.
     Context {A} (op: A -> A -> A) (init: A).
     Context (init_comm: forall a, op init a = op a init).
     Context (op_assoc: forall x y z, op (op x y) z = op x (op y z)).

Step 1: prove that init can be moved around:

.. coq::

     Lemma init_comm' l:
       forall a, fold_left op l (op init a) = op a (fold_left op l init).
     Proof.
       induction l. all: simpl. all: intros.
       - eauto using init_comm.
       - rewrite op_assoc.
         rewrite IHl.
         rewrite op_assoc.
         rewrite <- IHl.
         reflexivity.
     Qed.

Step 2: prove that fold_left and fold_right are equivalent.

.. coq::

     Goal forall l, fold_left op l init = fold_right op init l.
     Proof.
       intros. pose (l' := l).
       induction l. all: simpl. all: intros.
       - reflexivity.
       - rewrite <- IHl. rewrite init_comm'.
         reflexivity.
     Qed.
   End Folds.
