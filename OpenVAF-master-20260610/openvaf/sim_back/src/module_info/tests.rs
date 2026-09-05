use hir::diagnostics::sink::Buffer;
use hir::diagnostics::ConsoleSink;
use hir::CompilationDB;
use indoc::indoc;

#[test]
fn invalid_attr() {
    let src = indoc! {r#"
        module test;
            (* units=1, desc=xx, group=foo*bar, type=2  *) parameter real foo=2.0, bar=3.0;
            (* type="foo"  *) parameter real test=1.0;
            (* units=1, desc=xx *) real init;
            aliasparam alias=foo;
        endmodule
    "#};
    let db = CompilationDB::new_virtual(src).unwrap();
    let mut buf = Buffer::no_color();
    {
        let mut sink = ConsoleSink::buffer(&db, &mut buf);
        sink.annonymize_paths();
        super::collect_modules(&db, false, &mut sink);
    }
    expect_test::expect![[r#"
        error: illegal expression supplied to 'units' attribute; expected a string literal
          --> /root.va:2:8
          |
        2 |     (* units=1, desc=xx, group=foo*bar, type=2  *) parameter real foo=2.0, bar=3.0;
          |        ^^^^^^^ expected a string literal

        error: illegal expression supplied to 'desc' attribute; expected a string literal
          --> /root.va:2:17
          |
        2 |     (* units=1, desc=xx, group=foo*bar, type=2  *) parameter real foo=2.0, bar=3.0;
          |                 ^^^^^^^ expected a string literal

        error: illegal expression supplied to 'group' attribute; expected a string literal
          --> /root.va:2:26
          |
        2 |     (* units=1, desc=xx, group=foo*bar, type=2  *) parameter real foo=2.0, bar=3.0;
          |                          ^^^^^^^^^^^^^ expected a string literal

        error: illegal expression supplied to 'type' attribute; expected a string literal
          --> /root.va:2:41
          |
        2 |     (* units=1, desc=xx, group=foo*bar, type=2  *) parameter real foo=2.0, bar=3.0;
          |                                         ^^^^^^ expected a string literal

        warning: unknown type "foo" expected "model" or "instance"
          --> /root.va:3:8
          |
        3 |     (* type="foo"  *) parameter real test=1.0;
          |        ^^^^^^^^^^ unknown type

        error: illegal expression supplied to 'units' attribute; expected a string literal
          --> /root.va:4:8
          |
        4 |     (* units=1, desc=xx *) real init;
          |        ^^^^^^^ expected a string literal

        error: illegal expression supplied to 'desc' attribute; expected a string literal
          --> /root.va:4:17
          |
        4 |     (* units=1, desc=xx *) real init;
          |                 ^^^^^^^ expected a string literal

        error: could not compile `root.va` due to 6 previous errors; 1 warning emitted

    "#]]
    .assert_eq(&String::from_utf8(buf.into_inner()).unwrap());
}

#[test]
fn parameters() {
    let src = indoc! {r#"
        module test;
            (* units="m", desc="hmm", group="foo", type="instance" *) parameter real foo=2.0, bar=3.0;
            aliasparam alias=foo;
            (* type="model" *) parameter real module_param=3.0;
        endmodule
    "#};
    let db = CompilationDB::new_virtual(src).unwrap();
    let modules = super::collect_modules(&db, false, &mut ConsoleSink::new(&db)).unwrap();
    assert_eq!(modules.len(), 1);
    let params: Vec<_> = modules[0].params.iter().map(|(k, v)| (k.name(&db), v)).collect();
    expect_test::expect![[r#"
        [
            (
                "foo",
                ParamInfo {
                    name: "foo",
                    alias: [
                        "alias",
                    ],
                    unit: "m",
                    description: "hmm",
                    group: "foo",
                    is_instance: true,
                    instance_bounds: false,
                    stat: None,
                },
            ),
            (
                "bar",
                ParamInfo {
                    name: "bar",
                    alias: [],
                    unit: "m",
                    description: "hmm",
                    group: "foo",
                    is_instance: true,
                    instance_bounds: false,
                    stat: None,
                },
            ),
            (
                "module_param",
                ParamInfo {
                    name: "module_param",
                    alias: [],
                    unit: "",
                    description: "",
                    group: "",
                    is_instance: false,
                    instance_bounds: false,
                    stat: None,
                },
            ),
        ]
    "#]]
    .assert_debug_eq(&params);
}

#[test]
fn opvars() {
    let src = indoc! {r#"
        module test;
            (* units="m", desc="hmm" *) real both1, both2=3.0;
            (* units="m" *) real units_;
            (* desc="hmm" *) real desc_;
        endmodule
    "#};
    let db = CompilationDB::new_virtual(src).unwrap();
    let modules = super::collect_modules(&db, false, &mut ConsoleSink::new(&db)).unwrap();
    assert_eq!(modules.len(), 1);
    let params: Vec<_> = modules[0].op_vars.iter().map(|(k, v)| (k.name(&db), v)).collect();
    expect_test::expect![[r#"
        [
            (
                "both1",
                OpVar {
                    unit: "m",
                    description: "hmm",
                },
            ),
            (
                "both2",
                OpVar {
                    unit: "m",
                    description: "hmm",
                },
            ),
            (
                "units_",
                OpVar {
                    unit: "m",
                    description: "",
                },
            ),
            (
                "desc_",
                OpVar {
                    unit: "",
                    description: "hmm",
                },
            ),
        ]
    "#]]
    .assert_debug_eq(&params);
}

/// Enhancement-546 (compiler hunt F2): a parameter whose DEFAULT reads an
/// instance parameter is promoted to instance level, transitively, and the
/// promotion is named -- except for an untyped localparam. A parameter whose
/// BOUNDS alone read one keeps its level and is marked `instance_bounds`.
#[test]
fn instance_dependent_parameters() {
    let src = indoc! {r#"
        module test;
            (* type="instance" *) parameter real w = 1e-6 from (0:inf);
            parameter real l = 1e-6 from (0:w];
            localparam real l2 = 2*w;
            (* type="model" *) parameter real l3 = w + 1e-6;
            parameter real l4 = 2*l2;
            parameter integer g = $param_given(w) ? 1 : 0;
            parameter real m = 1.0;
            (* type="instance" *) parameter real w2 = 1e-6 from (0:w];
            (* openvaf_allow="instance_dependent_parameter" *) parameter real l5 = 3*w;
            (* type="model" *) localparam real l6 = l2;
            parameter real n = m from (0:m];
            parameter real k = 1e-6 from (0:l2] exclude l;
        endmodule
    "#};
    let db = CompilationDB::new_virtual(src).unwrap();
    let mut buf = Buffer::no_color();
    let modules = {
        let mut sink = ConsoleSink::buffer(&db, &mut buf);
        sink.annonymize_paths();
        super::collect_modules(&db, false, &mut sink)
    };
    expect_test::expect![[r#"
        warning[L028]: parameter 'l3' is declared (* type="model" *) but depends on instance parameter 'w'; it is treated as an instance parameter
          --> /root.va:5:39
          |
        5 |     (* type="model" *) parameter real l3 = w + 1e-6;
          |                                       ^^^^^^^^^^^^^ its default is resolved per instance, with that instance's 'w'
          |
          = a model parameter is resolved once per model card, where no instance's value exists yet; a default that reads an instance parameter has a value per instance, so the compiler resolves it in the instance setup, with that instance's values (a range that reads one is judged per instance either way, without moving the parameter)
          = help: declare it `(* type="instance" *)` to state the intent -- it stays settable on the .model card as the default for the card's instances -- or `(* openvaf_allow="instance_dependent_parameter" *)` to accept the promotion silently
          = instance_dependent_parameter is set to warn by default
            use a CLI argument or an attribute to overwrite

        warning[L028]: parameter 'l4' depends on instance parameter 'l2' and is treated as an instance parameter
          --> /root.va:6:20
          |
        6 |     parameter real l4 = 2*l2;
          |                    ^^^^^^^^^ its default is resolved per instance, with that instance's 'l2'
          |
          = a model parameter is resolved once per model card, where no instance's value exists yet; a default that reads an instance parameter has a value per instance, so the compiler resolves it in the instance setup, with that instance's values (a range that reads one is judged per instance either way, without moving the parameter)
          = help: declare it `(* type="instance" *)` to state the intent -- it stays settable on the .model card as the default for the card's instances -- or `(* openvaf_allow="instance_dependent_parameter" *)` to accept the promotion silently
          = instance_dependent_parameter is set to warn by default
            use a CLI argument or an attribute to overwrite

        warning[L028]: parameter 'g' depends on instance parameter 'w' and is treated as an instance parameter
          --> /root.va:7:23
          |
        7 |     parameter integer g = $param_given(w) ? 1 : 0;
          |                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^ its default is resolved per instance, with that instance's 'w'
          |
          = a model parameter is resolved once per model card, where no instance's value exists yet; a default that reads an instance parameter has a value per instance, so the compiler resolves it in the instance setup, with that instance's values (a range that reads one is judged per instance either way, without moving the parameter)
          = help: declare it `(* type="instance" *)` to state the intent -- it stays settable on the .model card as the default for the card's instances -- or `(* openvaf_allow="instance_dependent_parameter" *)` to accept the promotion silently
          = instance_dependent_parameter is set to warn by default
            use a CLI argument or an attribute to overwrite

        warning[L028]: localparam 'l6' is declared (* type="model" *) but depends on instance parameter 'l2'; it is treated as an instance parameter
           --> /root.va:11:40
           |
        11 |     (* type="model" *) localparam real l6 = l2;
           |                                        ^^^^^^^ its default is resolved per instance, with that instance's 'l2'
           |
           = a model parameter is resolved once per model card, where no instance's value exists yet; a default that reads an instance parameter has a value per instance, so the compiler resolves it in the instance setup, with that instance's values (a range that reads one is judged per instance either way, without moving the parameter)
           = help: nothing settable changes for a localparam; `(* openvaf_allow="instance_dependent_parameter" *)` on the declaration accepts the promotion silently
           = instance_dependent_parameter is set to warn by default
             use a CLI argument or an attribute to overwrite

        warning: `root.va` generated 4 warning

    "#]]
        .assert_eq(&String::from_utf8(buf.into_inner()).unwrap());
    let modules = modules.unwrap();
    assert_eq!(modules.len(), 1);
    let params: Vec<_> = modules[0]
        .params
        .iter()
        .map(|(k, v)| (k.name(&db), v.is_instance, v.instance_bounds))
        .collect();
    expect_test::expect![[r#"
        [
            (
                "w",
                true,
                false,
            ),
            (
                "l",
                false,
                true,
            ),
            (
                "l2",
                true,
                false,
            ),
            (
                "l3",
                true,
                false,
            ),
            (
                "l4",
                true,
                false,
            ),
            (
                "g",
                true,
                false,
            ),
            (
                "m",
                false,
                false,
            ),
            (
                "w2",
                true,
                true,
            ),
            (
                "l5",
                true,
                false,
            ),
            (
                "l6",
                true,
                false,
            ),
            (
                "n",
                false,
                false,
            ),
            (
                "k",
                false,
                true,
            ),
        ]
    "#]].assert_debug_eq(&params);
}
