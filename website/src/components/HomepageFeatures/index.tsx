import type {ReactNode} from 'react';
import clsx from 'clsx';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

type FeatureItem = {
  title: string;
  description: ReactNode;
};

const FeatureList: FeatureItem[] = [
  {
    title: 'MCP and Tools',
    description: (
      <>
        Local and remote registry, session warming, and integration with MCP servers to extend the
        agent without touching the core.
      </>
    ),
  },
  {
    title: 'STM / LTM Memory',
    description: (
      <>
        Session context, FTS history search, and LTM orchestration (MemPalace) for
        consistent responses over time.
      </>
    ),
  },
  {
    title: 'Clients and Admin',
    description: (
      <>
        FastAPI APIs, Chainlit interface, and Next.js dashboard in <code>admin-ui/</code> to
        manage profiles, skills, and security.
      </>
    ),
  },
];

function Feature({title, description}: FeatureItem) {
  return (
    <div className={clsx('col col--4')}>
      <div className={clsx('padding-horiz--md', styles.featureCard)}>
        <Heading as="h3" className={styles.featureTitle}>
          {title}
        </Heading>
        <p className={styles.featureDesc}>{description}</p>
      </div>
    </div>
  );
}

export default function HomepageFeatures(): ReactNode {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}
