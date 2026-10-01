;;; mcp_lib.lsp -- runtime used by the autocad MCP server (AutoCAD for Mac and Windows).
;;; Loaded before every request. Only core AutoLISP / vl- functions are used:
;;; vla-/vlax-/vlr- (ActiveX, reactors) do not exist on macOS.

;;; ---------- JSON serialization ----------

(defun mcp:hex2 (n / d)
  (setq d "0123456789abcdef")
  (strcat (substr d (1+ (/ n 16)) 1) (substr d (1+ (rem n 16)) 1))
)

(defun mcp:jstr (s)
  (strcat
    "\""
    (apply 'strcat
      (mapcar
        '(lambda (c)
           (cond
             ((= c 34) "\\\"")
             ((= c 92) "\\\\")
             ((= c 10) "\\n")
             ((= c 13) "\\r")
             ((= c 9) "\\t")
             ((< c 32) (strcat "\\u00" (mcp:hex2 c)))
             (t (chr c))
           )
         )
        (vl-string->list s)
      )
    )
    "\""
  )
)

(defun mcp:jreal (r / s)
  (setq s (rtos r 2 12))
  (cond
    ((= (substr s 1 1) ".") (setq s (strcat "0" s)))
    ((= (substr s 1 2) "-.") (setq s (strcat "-0" (substr s 2))))
  )
  s
)

(defun mcp:handle (e / d)
  (if (setq d (entget e)) (cdr (assoc 5 d)))
)

(defun mcp:jarr (items)
  (if items
    (strcat "[" (apply 'strcat (cons (car items) (mapcar '(lambda (x) (strcat "," x)) (cdr items)))) "]")
    "[]"
  )
)

(defun mcp:alist-p (x)
  (and (vl-list-length x)
       (vl-every '(lambda (p) (and (= (type p) 'LIST) (= (type (car p)) 'STR))) x))
)

(defun mcp:json (x / ty n i hs)
  (setq ty (type x))
  (cond
    ((null x) "null")
    ((= x T) "true")
    ((= ty 'INT) (itoa x))
    ((= ty 'REAL) (mcp:jreal x))
    ((= ty 'STR) (mcp:jstr x))
    ((= ty 'SYM) (mcp:jstr (vl-symbol-name x)))
    ((= ty 'ENAME)
     (if (mcp:handle x) (strcat "{\"handle\":" (mcp:jstr (mcp:handle x)) "}") "null"))
    ((= ty 'PICKSET)
     (setq n (sslength x) i 0 hs nil)
     (while (and (< i n) (< i 500))
       (setq hs (cons (mcp:jstr (mcp:handle (ssname x i))) hs) i (1+ i))
     )
     (strcat "{\"selection_count\":" (itoa n) ",\"handles\":" (mcp:jarr (reverse hs)) "}"))
    ((and (= ty 'LIST) (mcp:alist-p x))                      ; (("key" . value) ...) -> {"key": value}
     (strcat "{"
       (substr (apply 'strcat (mapcar '(lambda (p) (strcat "," (mcp:jstr (car p)) ":" (mcp:json (cdr p)))) x)) 2)
       "}"))
    ((= ty 'LIST)
     (if (vl-list-length x)
       (mcp:jarr (mapcar 'mcp:json x))
       (mcp:jarr (list (mcp:json (car x)) (mcp:json (cdr x))))   ; dotted pair -> [car, cdr]
     ))
    (t (mcp:jstr (vl-prin1-to-string x)))
  )
)

;;; ---------- request execution ----------

;; Unicode output needs the 3-argument open (AutoCAD 2021+); older releases fall back to ANSI.
(defun mcp:write (path text / f)
  (setq f (vl-catch-all-apply 'open (list path "w" "utf8")))
  (if (vl-catch-all-error-p f) (setq f (open path "w")))
  (write-line text f)
  (close f)
)

;; Lets tool code stop with its own message: (mcp:fail "no such entity").
(defun mcp:fail (msg)
  (setq *mcp-fail* msg)
  (exit)
)

;; Runs FN (a quoted lambda) with errors caught, as a single undo group,
;; and writes {"ok":..,"value":..,"repr":..} to the result file (atomically via rename).
;; AutoLISP is dynamically scoped: the caller's code runs inside this function and a plain
;; (setq out ...) there would overwrite our variables. Hence the *mcp-...* names.
(defun mcp:run (*mcp-out* *mcp-fn* *mcp-undo* / *mcp-res* *mcp-json* *mcp-echo* *mcp-tmp*)
  (setq *mcp-echo* (getvar "CMDECHO") *mcp-fail* nil)
  (setvar "CMDECHO" 0)
  (if (and *mcp-undo* (= 0 (getvar "CMDACTIVE"))) (command "_.UNDO" "_BEgin"))
  (setq *mcp-res* (vl-catch-all-apply *mcp-fn* nil))
  (while (> (getvar "CMDACTIVE") 0) (command ""))  ; close any command left open
  (if *mcp-undo* (command "_.UNDO" "_End"))
  (setvar "CMDECHO" *mcp-echo*)
  (setq *mcp-json*
    (if (vl-catch-all-error-p *mcp-res*)
      (strcat "{\"ok\":false,\"error\":" (mcp:jstr (if *mcp-fail* *mcp-fail* (vl-catch-all-error-message *mcp-res*))) "}")
      (strcat "{\"ok\":true,\"value\":"
              (mcp:json *mcp-res*)
              ",\"repr\":"
              (mcp:jstr (vl-prin1-to-string *mcp-res*))
              "}")
    )
  )
  (setq *mcp-tmp* (strcat *mcp-out* ".tmp"))
  (mcp:write *mcp-tmp* *mcp-json*)
  (vl-file-delete *mcp-out*)
  (vl-file-rename *mcp-tmp* *mcp-out*)
  (princ)
)

;;; ---------- helpers used by MCP tools ----------

;; Short description of an entity: handle, type, layer and main geometry.
(defun mcp:ent-summary (e / d g)
  (setq d (entget e))
  (setq g '(0 8 5 1 10 11 40 41 42 50 62 70 2 7))
  (vl-remove-if-not '(lambda (p) (member (car p) g)) d)
)

(defun mcp:ss->summaries (ss limit / i n out)
  (setq out nil i 0)
  (if ss
    (progn
      (setq n (sslength ss))
      (while (and (< i n) (< i limit))
        (setq out (cons (mcp:ent-summary (ssname ss i)) out) i (1+ i))
      )
      (list (cons "total" n) (cons "items" (reverse out)))
    )
    (list (cons "total" 0) (cons "items" nil))
  )
)

(defun mcp:table (name / r out)
  (setq out nil r (tblnext name T))
  (while r
    (setq out (cons r out) r (tblnext name))
  )
  (reverse out)
)

(defun mcp:layers (/ out)
  (mapcar
    '(lambda (r)
       (list
         (cons "name" (cdr (assoc 2 r)))
         (cons "color" (abs (cdr (assoc 62 r))))
         (cons "on" (>= (cdr (assoc 62 r)) 0))
         (cons "frozen" (= 1 (logand 1 (cdr (assoc 70 r)))))
         (cons "locked" (= 4 (logand 4 (cdr (assoc 70 r)))))
         (cons "linetype" (cdr (assoc 6 r)))
       )
     )
    (mcp:table "LAYER")
  )
)

(defun mcp:info (/ ss)
  (setq ss (ssget "_X"))
  (list
    (cons "dwgname" (getvar "DWGNAME"))
    (cons "dwgprefix" (getvar "DWGPREFIX"))
    (cons "saved" (= 0 (getvar "DBMOD")))
    (cons "acadver" (getvar "ACADVER"))
    (cons "insunits" (getvar "INSUNITS"))
    (cons "measurement" (getvar "MEASUREMENT"))
    (cons "clayer" (getvar "CLAYER"))
    (cons "extmin" (getvar "EXTMIN"))
    (cons "extmax" (getvar "EXTMAX"))
    (cons "space" (if (= 1 (getvar "TILEMODE")) "model" (getvar "CTAB")))
    (cons "entity_count" (if ss (sslength ss) 0))
    (cons "layers" (mapcar '(lambda (r) (cdr (assoc 2 r))) (mcp:table "LAYER")))
    (cons "blocks" (vl-remove-if '(lambda (n) (= (substr n 1 1) "*")) (mapcar '(lambda (r) (cdr (assoc 2 r))) (mcp:table "BLOCK"))))
    (cons "text_styles" (mapcar '(lambda (r) (cdr (assoc 2 r))) (mcp:table "STYLE")))
    (cons "linetypes" (mapcar '(lambda (r) (cdr (assoc 2 r))) (mcp:table "LTYPE")))
  )
)

(princ)
