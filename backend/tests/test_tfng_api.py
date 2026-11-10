import json
import os
from pathlib import Path
import pytest
from tests.test_ielts_pivot import ielts_client
from app.persistence.seed import import_content_pack


@pytest.fixture
def tfng_client(ielts_client, session_factory, monkeypatch):
    from app.model_provider.fake import FakeModelProvider
    def forbidden(*args, **kwargs):
        raise AssertionError("TFNG rule protocol must not invoke a model")
    monkeypatch.setattr(FakeModelProvider, "generate_structured", forbidden)
    with session_factory() as db:
        import_content_pack(db, pack_path=Path(__file__).parents[1] / 'app/content/ielts_tfng_diagnostic_pack.json')
        db.commit()
    return ielts_client


@pytest.mark.parametrize('variant,tag', [('academic','acad'),('general_training','gt')])
@pytest.mark.parametrize('loc,logic,target', [('B','FALSE','logic'),('A','NOT GIVEN','location'),('A','FALSE',None),('unsure','unsure',None),('B','NOT GIVEN',None)])
def test_tfng_api_paths(tfng_client, variant, tag, loc, logic, target):
    c=tfng_client
    trace=[]
    def call(method,url,body=None):
        r=getattr(c,method)(url,json=body) if body is not None else getattr(c,method)(url)
        assert r.status_code in (200,201),r.text
        data=r.json(); trace.append({'method':method,'url':url,'request':body,'response':data})
        return data
    call('put','/api/v1/profile/exam-preparation',{'exam_variant':variant})
    p=f'ielts-tfng-{tag}'
    session=call('post','/api/v1/sessions',{'topic_id':p+'-reading-english','exam_variant':variant})
    sid=session['id']
    assert 'standard_answer' not in session['current_question']
    body={'question_id':p+'-initial','submitted_answer':'FALSE','idempotency_key':f'{tag}-{loc}-{logic}-initial'}
    attempt=call('post',f'/api/v1/sessions/{sid}/attempts',body)
    repeated=call('post',f'/api/v1/sessions/{sid}/attempts',body)
    assert repeated['attempt_id']==attempt['attempt_id']
    case=attempt['diagnostic_case_id']
    first=call('post',f'/api/v1/diagnoses/{case}/step',{'idempotency_key':f'{sid}-step1'})
    assert first['next_question']['id']==p+'-locate'
    assert first['execution_mode']=='rules'
    replay=call('post',f'/api/v1/diagnoses/{case}/step',{'idempotency_key':f'{sid}-step1'})
    assert replay['selected_question_id']==first['selected_question_id']
    assert replay['followup_turns_used']==1
    hs=call('get',f'/api/v1/diagnoses/{case}/hypotheses')
    assert len(hs)>=2
    for suffix,answer,n in [('locate',loc,2),('logic',logic,3)]:
        call('post',f'/api/v1/sessions/{sid}/attempts',{'question_id':p+'-'+suffix,'submitted_answer':answer,'idempotency_key':f'{sid}-{suffix}'})
        # Restoration reads the same server session, never a local diagnostic counter.
        restored=call('get',f'/api/v1/sessions/{sid}')
        assert restored['active_diagnostic_case_id']==case
        assert call('get',f'/api/v1/diagnoses/{case}')['execution_mode']=='rules'
        result=call('post',f'/api/v1/diagnoses/{case}/step',{'idempotency_key':f'{sid}-step{n}'})
        if suffix=='locate': assert result['next_question']['id']==p+'-logic'
    hs=call('get',f'/api/v1/diagnoses/{case}/hypotheses')
    evidence=call('get',f'/api/v1/diagnoses/{case}/evidence')
    assert all(h['status']!='confirmed' for h in hs)
    if target:
        assert result['next_question']['id']==p+'-practice-'+target
        assert ('true_false_not_given' if target=='logic' else 'passage_location') in result['decision_reason']
        states={h['error_code']:h['status'] for h in hs}
        assert states['true_false_not_given']==('supported' if target=='logic' else 'lowered')
        assert states['passage_location']==('supported' if target=='location' else 'lowered')
        assert any(e['relation']=='contradicts' for e in evidence)
    else:
        assert result['next_question'] is None
        assert result['case_status']=='insufficient_evidence'
    assert all('evaluation_rubric' not in x.get('response',{}).get('next_question',{}) for x in trace if isinstance(x.get('response'),dict) and x['response'].get('next_question'))
    if os.getenv('TFNG_TRACE_DIR'):
        out=Path(os.environ['TFNG_TRACE_DIR']);out.mkdir(parents=True,exist_ok=True)
        (out/f'{tag}-{target or ("both" if loc=="A" else "resolved" if logic=="NOT GIVEN" else "unavailable" if loc=="B" else "unknown")}.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')


def test_missing_matching_practice_never_selects_first_question(tfng_client, session_factory):
    from app.persistence.models import Question
    with session_factory() as db:
        db.delete(db.get(Question, "ielts-tfng-acad-practice-logic"))
        db.commit()
    test_tfng_api_paths(tfng_client, "academic", "acad", "B", "FALSE", None)
