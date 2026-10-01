;;; house.lsp -- small one-storey house plan 10 x 8 m (units: mm).
;;; Run through the MCP: autocad_eval_lisp with this file's contents.

(defun h:layer (name color)
  (if (not (tblsearch "LAYER" name))
    (entmake (list '(0 . "LAYER") '(100 . "AcDbSymbolTableRecord") '(100 . "AcDbLayerTableRecord")
                   (cons 2 name) '(70 . 0) (cons 62 color) '(6 . "Continuous")))
  )
)

(defun h:pline (pts layer closed)
  (entmake
    (append
      (list '(0 . "LWPOLYLINE") '(100 . "AcDbEntity") (cons 8 layer) '(100 . "AcDbPolyline")
            (cons 90 (length pts)) (cons 70 (if closed 1 0)))
      (mapcar '(lambda (p) (cons 10 p)) pts)
    )
  )
)

(defun h:line (a b layer)
  (entmake (list '(0 . "LINE") (cons 8 layer) (cons 10 a) (cons 11 b)))
)

;; Filled rectangle: 2D SOLID (corner order 1-2-4-3) + outline
(defun h:rect (x1 y1 x2 y2 layer)
  (entmake (list '(0 . "SOLID") (cons 8 layer) '(62 . 8)
                 (list 10 x1 y1 0.0) (list 11 x2 y1 0.0) (list 12 x1 y2 0.0) (list 13 x2 y2 0.0)))
  (h:pline (list (list x1 y1) (list x2 y1) (list x2 y2) (list x1 y2)) layer T)
)

;; Wall rectangle with openings (list of (from to) along its long axis)
(defun h:wall (x1 y1 x2 y2 openings / horiz a cuts)
  (setq horiz (> (- x2 x1) (- y2 y1)))
  (setq a (if horiz x1 y1))
  (foreach o (vl-sort openings '(lambda (p q) (< (car p) (car q))))
    (if horiz (h:rect a y1 (car o) y2 "СТЕНЫ") (h:rect x1 a x2 (car o) "СТЕНЫ"))
    (setq a (cadr o))
  )
  (if horiz (h:rect a y1 x2 y2 "СТЕНЫ") (h:rect x1 a x2 y2 "СТЕНЫ"))
)

;; Window in an exterior wall opening: frame + glass line
(defun h:window (x1 y1 x2 y2 / horiz m)
  (h:pline (list (list x1 y1) (list x2 y1) (list x2 y2) (list x1 y2)) "ОКНА" T)
  (setq horiz (> (- x2 x1) (- y2 y1)))
  (if horiz
    (progn (setq m (/ (+ y1 y2) 2.0)) (h:line (list x1 m) (list x2 m) "ОКНА"))
    (progn (setq m (/ (+ x1 x2) 2.0)) (h:line (list m y1) (list m y2) "ОКНА"))
  )
)

;; Door: hinge point, width, leaf angle and closed angle (degrees), arc between them (ccw from a1 to a2)
(defun h:door (hx hy w leaf a1 a2 / r)
  (setq r (* pi (/ leaf 180.0)))
  (h:line (list hx hy) (list (+ hx (* w (cos r))) (+ hy (* w (sin r)))) "ДВЕРИ")
  (entmake (list '(0 . "ARC") '(8 . "ДВЕРИ") (list 10 hx hy 0.0) (cons 40 w)
                 (cons 50 (* pi (/ a1 180.0))) (cons 51 (* pi (/ a2 180.0)))))
)

(defun h:text (x y h s layer)
  (entmake (list '(0 . "TEXT") (cons 8 layer) (list 10 x y 0.0) (list 11 x y 0.0)
                 (cons 40 h) (cons 1 s) '(72 . 1) '(73 . 2)))
)

(defun h:room (name x1 y1 x2 y2 / cx cy)
  (setq cx (/ (+ x1 x2) 2.0) cy (/ (+ y1 y2) 2.0))
  (h:text cx (+ cy 180) 250 name "ТЕКСТ")
  (h:text cx (- cy 220) 200 (strcat (rtos (/ (* (- x2 x1) (- y2 y1)) 1e6) 2 1) " м²") "ТЕКСТ")
)

;; ---------- layers
(h:layer "СТЕНЫ" 7)
(h:layer "ОКНА" 4)
(h:layer "ДВЕРИ" 3)
(h:layer "ТЕКСТ" 2)
(h:layer "РАЗМЕРЫ" 1)

;; ---------- exterior walls (300)
(h:wall 0 0 10000 300 '((1500 2700) (7500 8400)))                     ; south: kitchen window, entrance
(h:wall 0 7700 10000 8000 '((1500 3000) (5500 6600) (7800 9000)))     ; north: living, kids, bedroom windows
(h:wall 0 300 300 7700 '((1000 2200) (5000 6500)))                    ; west: kitchen, living windows
(h:wall 9700 300 10000 7700 '((900 1800) (4500 6000)))                ; east: hall, bedroom windows

;; ---------- partitions (150)
(h:wall 5000 300 5150 7700 '((1000 1900) (5800 6700)))                ; A: kitchen|hall, living|kids
(h:wall 300 3150 5000 3300 '((1500 3000)))                            ; B: kitchen|living, arch
(h:wall 5150 2700 9700 2850 '((5600 6400) (8000 8900)))               ; C: hall|bath, hall|bedroom
(h:wall 7000 2850 7150 7700 nil)                                      ; D: bath/kids|bedroom
(h:wall 5150 5000 7000 5150 nil)                                      ; E: bath|kids

;; ---------- windows
(h:window 1500 0 2700 300)
(h:window 1500 7700 3000 8000)
(h:window 5500 7700 6600 8000)
(h:window 7800 7700 9000 8000)
(h:window 0 1000 300 2200)
(h:window 0 5000 300 6500)
(h:window 9700 900 10000 1800)
(h:window 9700 4500 10000 6000)

;; ---------- doors
(h:door 7500 300 900 90 0 90)       ; entrance, opens into hall
(h:door 5150 1000 900 0 0 90)       ; hall -> kitchen
(h:door 5600 2850 800 90 0 90)      ; hall -> bathroom
(h:door 8900 2850 900 90 90 180)    ; hall -> bedroom
(h:door 5150 6700 900 0 270 360)    ; living -> kids room

;; ---------- rooms
(h:room "Гостиная" 300 3300 5000 7700)
(h:room "Кухня" 300 300 5000 3150)
(h:room "Прихожая" 5150 300 9700 2700)
(h:room "Санузел" 5150 2850 7000 5000)
(h:room "Детская" 5150 5150 7000 7700)
(h:room "Спальня" 7150 2850 9700 7700)
(h:text 5000 9300 400 "План дома 10 × 8 м" "ТЕКСТ")

;; ---------- dimensions
(setvar "DIMSCALE" 100)
(setvar "CLAYER" "РАЗМЕРЫ")
(command "_.DIMLINEAR" '(0 0) '(10000 0) '(5000 -1000))
(command "_.DIMLINEAR" '(0 0) '(0 8000) '(-1000 4000))
(command "_.DIMLINEAR" '(0 8000) '(5000 8000) '(2500 8700))
(command "_.DIMLINEAR" '(5000 8000) '(10000 8000) '(7500 8700))
(setvar "CLAYER" "0")
(command "_.ZOOM" "_E")
(command "_.ZOOM" "0.8x")
"house done"
